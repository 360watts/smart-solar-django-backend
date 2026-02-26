from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework.parsers import JSONParser, FormParser, MultiPartParser, BaseParser
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.shortcuts import get_object_or_404
from django.db import models, connection
from django.db.models import Q, Avg, Sum, Count, F
from django.db.models.functions import Coalesce
from django.conf import settings
from django.views.decorators.cache import cache_page
from django_ratelimit.decorators import ratelimit
from typing import Any
from django.utils import timezone
from decouple import config as env_config
from .serializers import (
    ProvisionSerializer,
    GatewayConfigSerializer,
    TelemetryIngestSerializer,
    TelemetryDataSerializer,
    DeviceSerializer,
)
from .models import Device, TelemetryData, GatewayConfig, UserProfile, SlaveDevice, RegisterMapping, DeviceLog
from ota.models import DeviceTargetedFirmware
import logging
import jwt
import secrets
import traceback
from datetime import datetime, timedelta, timezone as dt_timezone

# Get JWT secret from environment variable with secure fallback
DEVICE_JWT_SECRET = env_config('DEVICE_JWT_SECRET', default=settings.SECRET_KEY)

logger = logging.getLogger(__name__)


# ============== CUSTOM PARSERS ==============

class PlainTextParser(BaseParser):
    """
    Parser that accepts any content and doesn't fail on invalid JSON.
    Used for device log endpoints where ESP32 might send plain text.
    Tries to parse as JSON first, falls back to plain text.
    """
    media_type = '*/*'
    
    def parse(self, stream, media_type=None, parser_context=None):
        """
        Try JSON parsing first, fall back to plain text if that fails.
        """
        import json
        try:
            data = stream.read()
            # Try to parse as JSON first
            try:
                return json.loads(data.decode('utf-8'))
            except (json.JSONDecodeError, ValueError):
                # Fall back to plain text
                return data.decode('utf-8')
        except Exception as e:
            logger.warning(f"PlainTextParser failed to decode: {e}")
            return ""


# ============== AUDIT TRAIL UTILITIES ==============

def set_audit_fields(instance, request):
    """
    Helper function to automatically set created_by and updated_by fields.
    Sets created_by if not already set (for new instances).
    Always sets updated_by on any save.
    Safely handles cases where fields don't exist yet (pre-migration).
    """
    if request and hasattr(request, 'user') and request.user.is_authenticated:
        try:
            # Set created_by if it's not set yet (new object or never had created_by)
            if hasattr(instance, 'created_by') and not instance.created_by:
                instance.created_by = request.user
            if hasattr(instance, 'updated_by'):
                instance.updated_by = request.user
        except AttributeError:
            # Fields don't exist yet (migration not applied)
            pass
    return instance


# ============== CUSTOM PERMISSIONS ==============

class IsStaffUser(IsAuthenticated):
    """
    Permission class that allows only staff users
    """
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.is_staff


class DeviceAuthentication:
    """
    Custom authentication for device JWT tokens.
    Validates device JWT and sets request.device_id
    """
    @staticmethod
    def authenticate_device(request, device_id=None):
        """
        Validate device JWT token from Authorization header or query params.
        Returns (True, device_id) if valid, (False, error_message) if invalid.
        
        Security validations:
        - Token presence and format
        - JWT signature and expiration
        - Token type verification
        - Device ID matching
        - Device existence check
        - Token age validation (prevent very old provisioning tokens)
        """
        # Get token from Authorization header or query params
        auth_header = request.headers.get('Authorization', '')
        token = None
        
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
        elif 'token' in request.GET:
            token = request.GET.get('token')
        elif isinstance(request.data, dict) and 'secret' in request.data:
            token = request.data.get('secret')
        
        if not token:
            logger.warning(f"Device auth failed: Missing token. Device: {device_id}, IP: {request.META.get('REMOTE_ADDR')}")
            return False, 'Missing device authentication token'
        
        try:
            # Decode and validate JWT (checks signature and expiration automatically)
            payload = jwt.decode(token, DEVICE_JWT_SECRET, algorithms=["HS256"])
            
            # Check token type
            if payload.get('type') != 'device':
                logger.warning(f"Device auth failed: Invalid token type '{payload.get('type')}'. Device: {device_id}")
                return False, 'Invalid token type'
            
            # Get device_id from payload
            token_device_id = payload.get('device_id')
            if not token_device_id:
                logger.warning(f"Device auth failed: No device_id in token. Device: {device_id}")
                return False, 'Device ID not found in token'
            
            # If device_id provided in URL/request, verify it matches token
            if device_id and device_id != token_device_id:
                logger.warning(f"Device auth failed: ID mismatch. Token: {token_device_id}, Request: {device_id}, IP: {request.META.get('REMOTE_ADDR')}")
                return False, f'Device ID mismatch: token={token_device_id}, request={device_id}'
            
            # Validate token age (issued at time) - reject tokens older than 2 years
            iat = payload.get('iat')
            if iat:
                token_age_days = (datetime.now().timestamp() - iat) / 86400
                if token_age_days > 730:  # 2 years
                    logger.warning(f"Device auth failed: Token too old ({token_age_days:.0f} days). Device: {token_device_id}")
                    return False, 'Device token is too old, please re-provision'
            
            # Check if device exists and get its status
            try:
                device = Device.objects.get(device_serial=token_device_id)
                
                # Future enhancement: Check if device is disabled/blocked
                # if hasattr(device, 'is_active') and not device.is_active:
                #     logger.warning(f"Device auth failed: Device disabled. Device: {token_device_id}")
                #     return False, f'Device {token_device_id} has been disabled'
                
            except Device.DoesNotExist:
                logger.warning(f"Device auth failed: Device not found. Device: {token_device_id}, IP: {request.META.get('REMOTE_ADDR')}")
                return False, f'Device {token_device_id} not found'
            
            # Log successful authentication for audit trail
            logger.debug(f"Device auth success: {token_device_id} from {request.META.get('REMOTE_ADDR')}")
            
            return True, token_device_id
            
        except jwt.ExpiredSignatureError:
            logger.warning(f"Device auth failed: Expired token. Device: {device_id}, IP: {request.META.get('REMOTE_ADDR')}")
            return False, 'Device token has expired'
        except jwt.InvalidTokenError as e:
            logger.warning(f"Device auth failed: Invalid token ({str(e)}). Device: {device_id}, IP: {request.META.get('REMOTE_ADDR')}")
            return False, f'Invalid device token: {str(e)}'
        except Exception as e:
            logger.error(f"Device authentication error: {str(e)}. Device: {device_id}, IP: {request.META.get('REMOTE_ADDR')}", exc_info=True)
            return False, 'Device authentication failed'


@api_view(["POST"])
@permission_classes([AllowAny])
@ratelimit(key='ip', rate='10/m', block=True)
def provision(request: Any) -> Response:
    """
    Provision endpoint: /api/devices/provision
    ESP32 sends: {"hwId": "MAC", "model": "esp32 wroom", "claimNonce": "IM_YOUR_DEVICE"}
    ESP32 expects: {"status": "success", "deviceId": "...", "provisionedAt": "...", "credentials": {...}}
    Rate limited: 10 provisions per minute per IP
    """
    logger.info(f"Provision request: {request.data}")
    
    serializer = ProvisionSerializer(data=request.data)
    if not serializer.is_valid():
        logger.error(f"Validation errors: {serializer.errors}")
        return Response({"status": "error", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
    
    data = serializer.validated_data
    
    # Check for duplicate MAC address (hw_id must be unique)
    hw_id = data.get('hwId', '').strip()
    if hw_id:
        existing_device = Device.objects.filter(hw_id=hw_id).first()
        if existing_device:
            logger.warning(f"Provision attempt with duplicate MAC: {hw_id} (already used by device {existing_device.device_serial})")
            return Response(
                {
                    "status": "error", 
                    "error": "Duplicate MAC address",
                    "message": f"A device with MAC address {hw_id} already exists (Device ID: {existing_device.device_serial})"
                },
                status=status.HTTP_409_CONFLICT
            )
    
    # Generate random deviceId
    device_id = secrets.token_hex(6).upper()
    
    # Generate JWT token as credentials using secure secret from environment
    jwt_payload = {
        "device_id": device_id,
        "iat": int(datetime.now().timestamp()),
        "exp": int((datetime.now() + timedelta(days=365)).timestamp()),  # 1 year expiry
        "type": "device"
    }
    token = jwt.encode(jwt_payload, DEVICE_JWT_SECRET, algorithm="HS256")
    
    # Get or create system user for auto-provisioned devices (as staff/employee)
    system_user, _ = User.objects.get_or_create(
        username="system",
        defaults={
            "email": "system@devices.local",
            "is_staff": True,
            "is_active": True,
            "first_name": "System",
            "last_name": "Auto-Provision"
        }
    )
    # Ensure system user is staff even if it already existed
    if not system_user.is_staff:
        system_user.is_staff = True
        system_user.save()
    
    # Check for MAC address conflicts (hw_id uniqueness)
    hw_id = data.get('hwId', '').strip()
    if hw_id:
        existing_device_with_mac = Device.objects.filter(hw_id=hw_id).exclude(device_serial=device_id).first()
        if existing_device_with_mac:
            logger.error(f"MAC address conflict: {hw_id} already registered to device {existing_device_with_mac.device_serial}")
            return Response(
                {
                    "status": "error",
                    "error": "MAC address already registered",
                    "message": f"The MAC address {hw_id} is already registered to another device"
                },
                status=status.HTTP_409_CONFLICT
            )
    
    # Create or get device
    device, created = Device.objects.get_or_create(
        device_serial=device_id,
        defaults={
            "created_by": system_user
        }
    )
    if created:
        device.provisioned_at = timezone.now()
        device.created_by = system_user
        device.updated_by = system_user
    # Always update hw_id and model so re-provisioning keeps them current
    device.hw_id = hw_id
    device.model = data.get('model', '')
    device.save()
    
    logger.info(f"Device {'created' if created else 'found'}: {device_id}")
    
    # Return response matching ESP32 expectation with JWT token
    return Response(
        {
            "status": "success",
            "deviceId": device_id,
            "provisionedAt": device.provisioned_at.isoformat(),
            "credentials": {
                "type": "jwt",
                "secret": token,
                "expiresIn": 31536000  # 1 year in seconds
            }
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def gateway_config(request: Any, device_id: str) -> Response:
    """
    Config endpoint: /api/devices/{device_id}/config
    ESP32 sends: {"deviceId": "...", "firmwareVersion": "...", "configVersion": "..."}
    ESP32 expects complete config with uartConfig, slaves, registers
    Requires device JWT authentication
    """
    try:
        # Authenticate device
        is_valid, result = DeviceAuthentication.authenticate_device(request, device_id)
        if not is_valid:
            logger.warning(f"Config request failed authentication from {device_id}: {result}")
            return Response({"error": result}, status=status.HTTP_401_UNAUTHORIZED)

        logger.info(f"Config request from {device_id}: {request.data}")

        # Verify device exists
        device, _ = Device.objects.get_or_create(device_serial=device_id)

        # Check if device has a user assigned
        if not device.user:
            logger.warning(f"Device {device_id} has no user assigned")
            return Response(
                {"error": "Device not configured", "message": "Device must have a user assigned before configuration can be retrieved"},
                status=status.HTTP_403_FORBIDDEN
            )

        # Check if device has a gateway config assigned
        if not device.config_version:
            logger.warning(f"Device {device_id} has no gateway configuration assigned")
            return Response(
                {"error": "Device not configured", "message": "Device must have a gateway configuration (preset) assigned before configuration can be retrieved"},
                status=status.HTTP_403_FORBIDDEN
            )

        # Get the specific config for this device
        config = GatewayConfig.objects.filter(config_id=device.config_version).first()
        if not config:
            logger.warning(f"Configuration {device.config_version} not found for device {device_id}")
            return Response(
                {"error": "Configuration not found", "message": f"Assigned configuration {device.config_version} does not exist"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Serialize and return (config_version already set via admin/app)
        data = GatewayConfigSerializer(config).data
        logger.info(f"Sending config {config.config_id} to device {device_id}")

        # Clear the pending_config_update flag — device has received the latest config
        # Also record the download timestamp
        if device.pending_config_update:
            device.pending_config_update = False
            device.config_downloaded_at = timezone.now()
            device.save(update_fields=['pending_config_update', 'config_downloaded_at'])
        else:
            device.config_downloaded_at = timezone.now()
            device.save(update_fields=['config_downloaded_at'])

        return Response(data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"gateway_config error for device {device_id}: {e}", exc_info=True)
        return Response(
            {"error": "Internal server error", "detail": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@permission_classes([AllowAny])
def config_ack(request: Any, device_id: str) -> Response:
    """
    Config acknowledgment endpoint: /api/devices/{device_id}/configAck
    ESP32 sends after successfully writing config to flash:
      {"status": 1, "cfgVer": <int>}
    Backend records the acknowledged version so heartbeat can detect future changes.
    """
    is_valid, result = DeviceAuthentication.authenticate_device(request, device_id)
    if not is_valid:
        return Response({"error": result}, status=status.HTTP_401_UNAUTHORIZED)

    ack_status = request.data.get("status", 0)
    cfg_ver = request.data.get("cfgVer")

    if ack_status != 1 or cfg_ver is None:
        return Response({"error": "Invalid ack payload"}, status=status.HTTP_400_BAD_REQUEST)

    device, _ = Device.objects.get_or_create(device_serial=device_id)
    device.config_ack_ver = int(cfg_ver)
    device.pending_config_update = False  # device confirmed config written to flash
    device.config_acked_at = timezone.now()
    device.save(update_fields=["config_ack_ver", "pending_config_update", "config_acked_at"])

    logger.info(f"Config ack from {device_id}: cfgVer={cfg_ver}")
    return Response({"status": "ok"}, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([AllowAny])
def heartbeat(request: Any, device_id: str) -> Response:
    """
    Heartbeat endpoint: /api/devices/{device_id}/heartbeat
    ESP32 sends: {"deviceId": "...", "uptimeSeconds": ..., "firmwareVersion": "...", ...}
    ESP32 expects: {"status": 1, "commands": {"updateConfig": 0/1, "reboot": 0/1, "hardReset": 0/1, ...}}
    Requires device JWT authentication
    """
    # Authenticate device
    is_valid, result = DeviceAuthentication.authenticate_device(request, device_id)
    if not is_valid:
        logger.warning(f"Heartbeat failed authentication from {device_id}: {result}")
        return Response({"error": result}, status=status.HTTP_401_UNAUTHORIZED)
    
    # Log only sanitized, non-sensitive data (exclude JWT secret)
    sanitized_data = {k: v for k, v in request.data.items() if k != 'secret'}
    logger.info(f"Heartbeat from {device_id}: {sanitized_data}")
    
    # Get device
    device, _ = Device.objects.get_or_create(device_serial=device_id)
    
    # Update last heartbeat timestamp
    device.last_heartbeat = timezone.now()
    device.save(update_fields=['last_heartbeat'])
    
    # Get device's current config from request
    current_config_id = request.data.get("configId", "")
    
    # Determine if config update is needed
    update_config_needed = 0
    
    # Check if device has an assigned config
    if device.config_version:
        # Layer 1: config ID mismatch (different preset assigned)
        if current_config_id != device.config_version:
            update_config_needed = 1
            logger.info(f"Config update needed: device has '{current_config_id}', assigned is '{device.config_version}'")
        else:
            # Layer 2a: explicit flag — set whenever preset or slave content changes
            if device.pending_config_update:
                update_config_needed = 1
                logger.info(f"Config update needed: pending_config_update flag set for device {device_id}")
            else:
                # Layer 2b: cfgVer safety net — catches any missed flag resets
                try:
                    assigned_config = GatewayConfig.objects.get(config_id=device.config_version)
                    if device.config_ack_ver is None or assigned_config.version != device.config_ack_ver:
                        update_config_needed = 1
                        logger.info(
                            f"Config update needed (cfgVer mismatch): config '{device.config_version}' "
                            f"version={assigned_config.version}, acked={device.config_ack_ver}"
                        )
                except GatewayConfig.DoesNotExist:
                    logger.warning(f"Assigned config {device.config_version} not found for device {device_id}")
    else:
        # No config assigned yet
        if current_config_id:
            update_config_needed = 1
            logger.info(f"Config update needed: device has '{current_config_id}' but no config assigned on backend")
    
    # Check for pending reboot command
    reboot_needed = 1 if device.pending_reboot else 0
    if reboot_needed:
        logger.info(f"Reboot command queued for device {device_id}")
        # Clear the flag after sending command once
        device.pending_reboot = False
        device.save(update_fields=['pending_reboot'])
    
    # Check for pending hard reset command
    hard_reset_needed = 1 if device.pending_hard_reset else 0
    if hard_reset_needed:
        logger.info(f"Hard reset command queued for device {device_id}")
        # Clear the flag after sending command once
        device.pending_hard_reset = False
        device.save(update_fields=['pending_hard_reset'])
    
    # Check for pending firmware update (OTA)
    update_firmware_needed = 0
    
    # First check for rollback flag (highest priority)
    if device.pending_rollback:
        update_firmware_needed = 2  # Rollback command
        logger.info(f"Firmware rollback command queued for device {device_id}")
        # Clear the flag after sending command once
        device.pending_rollback = False
        device.save(update_fields=['pending_rollback'])
    else:
        # Check for targeted firmware update
        try:
            if hasattr(device, 'targeted_firmware') and device.targeted_firmware.is_active:
                # Only return update command for non-rollback targeted updates
                if not device.targeted_firmware.is_rollback:
                    update_firmware_needed = 1  # New firmware update
                    logger.info(f"Firmware update available for device {device_id}: {device.targeted_firmware.target_firmware.version}")
        except DeviceTargetedFirmware.DoesNotExist:
            pass
    
    # Check if device should send logs
    send_logs = 1 if device.logs_enabled else 0
    
    # Build response with commands
    response_data = {
        "status": 1,  # ESP32 checks for status == 1
        "serverTime": timezone.now().isoformat(),
        "commands": {
            "updateConfig": update_config_needed,
            "reboot": reboot_needed,
            "hardReset": hard_reset_needed,
            "updateFirmware": update_firmware_needed,
            "sendLogs": send_logs,
        },
        "message": "OK"
    }
    
    return Response(response_data, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([AllowAny])
@parser_classes([PlainTextParser])
def logs(request: Any, device_id: str) -> Response:
    """
    Logs endpoint: /api/devices/{device_id}/logs or /api/devices/{device_id}/deviceLogs
    ESP32 sends log data when sendLogs is enabled in heartbeat
    Accepts both JSON format {"logs": [...]} and plain text log messages
    Requires device JWT authentication
    """
    logger.info(f"Logs endpoint hit from {device_id}, Content-Type: {request.content_type}, Data type: {type(request.data)}")
    
    # Authenticate device
    is_valid, result = DeviceAuthentication.authenticate_device(request, device_id)
    if not is_valid:
        logger.warning(f"Logs upload failed authentication from {device_id}: {result}")
        return Response({"error": result}, status=status.HTTP_401_UNAUTHORIZED)
    
    try:
        device = Device.objects.get(device_serial=device_id)
    except Device.DoesNotExist:
        logger.error(f"Device not found: {device_id}")
        return Response({'error': 'Device not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Extract log data from request - handle both JSON and plain text
    logs_data = []
    try:
        logger.info(f"Request data from {device_id}: {request.data}")
        
        # Check if request.data is a string (from PlainTextParser)
        if isinstance(request.data, str):
            body_text = request.data.strip()
            if body_text:
                logs_data = [{
                    'level': 'INFO',
                    'message': body_text,
                    'metadata': {}
                }]
        # Try to parse as JSON dict
        elif isinstance(request.data, dict):
            # Check if it has a 'logs' key with actual data
            if 'logs' in request.data and request.data['logs']:
                logs_data = request.data['logs']
                if not isinstance(logs_data, list):
                    logs_data = [logs_data]
            else:
                # No 'logs' key or empty - treat entire dict as a single log entry
                # Filter out authentication fields
                log_entry = {k: v for k, v in request.data.items() if k not in ['secret', 'deviceId']}
                if log_entry:
                    # Extract level and message if present, otherwise convert to string
                    level = log_entry.pop('level', 'INFO')
                    message = log_entry.pop('message', str(request.data))
                    logs_data = [{
                        'level': level,
                        'message': message,
                        'metadata': log_entry
                    }]
        elif isinstance(request.data, list):
            logs_data = request.data
        else:
            # Last fallback to raw body
            body_text = request.body.decode('utf-8') if isinstance(request.body, bytes) else str(request.body)
            if body_text and body_text.strip():
                logs_data = [{
                    'level': 'INFO',
                    'message': body_text.strip(),
                    'metadata': {}
                }]
        
        logger.info(f"Parsed {len(logs_data)} log entries from {device_id}")
    except Exception as e:
        logger.error(f"Failed to parse logs data from {device_id}: {e}, traceback: {traceback.format_exc()}")
        # Even on parse error, try to save the raw body as a log
        try:
            body_text = request.body.decode('utf-8') if isinstance(request.body, bytes) else str(request.body)
            if body_text and body_text.strip():
                logs_data = [{
                    'level': 'ERROR',
                    'message': f"Parse error - raw content: {body_text[:500]}",
                    'metadata': {'parse_error': str(e)}
                }]
        except:
            return Response({"error": f"Invalid log data format: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
    
    # Save logs to database
    saved_count = 0
    for log_entry in logs_data:
        if isinstance(log_entry, dict):
            DeviceLog.objects.create(
                device=device,
                log_level=log_entry.get('level', 'INFO'),
                message=log_entry.get('message', ''),
                metadata=log_entry.get('metadata', {})
            )
            saved_count += 1
    
    logger.info(f"Logs from {device_id}: {saved_count}/{len(logs_data)} items stored")
    return Response({"status": "stored", "count": saved_count}, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([AllowAny])
@ratelimit(key='ip', rate='100/m', block=True)
def telemetry_ingest(request: Any) -> Response:
    """
    Ingest telemetry data. Rate limited: 100 requests per minute per IP
    Requires device JWT authentication
    """
    # Extract device_id from request data
    device_id = request.data.get('deviceId')
    if not device_id:
        return Response({"error": "deviceId is required"}, status=status.HTTP_400_BAD_REQUEST)
    
    # Authenticate device
    is_valid, result = DeviceAuthentication.authenticate_device(request, device_id)
    if not is_valid:
        logger.warning(f"Telemetry ingest failed authentication from {device_id}: {result}")
        return Response({"error": result}, status=status.HTTP_401_UNAUTHORIZED)
    
    serializer = TelemetryIngestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    telemetry = serializer.save()
    return Response({"status": "stored", "id": telemetry.id}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([AllowAny])
def telemetry_latest(request: Any, device_serial: str) -> Response:
    """
    Get latest telemetry for a device.
    Requires device JWT authentication matching the device_serial.
    """
    # Authenticate device
    is_valid, result = DeviceAuthentication.authenticate_device(request, device_serial)
    if not is_valid:
        logger.warning(f"Telemetry fetch failed authentication for {device_serial}: {result}")
        return Response({"error": result}, status=status.HTTP_401_UNAUTHORIZED)
    
    try:
        limit = int(request.GET.get("limit", 10))
    except (ValueError, TypeError):
        return Response({"error": "Invalid limit parameter. Must be an integer."}, status=status.HTTP_400_BAD_REQUEST)
    
    qs = TelemetryData.objects.filter(device__device_serial=device_serial).order_by("-timestamp")[:limit]
    return Response(TelemetryDataSerializer(qs, many=True).data)


@api_view(["GET"])
@permission_classes([IsStaffUser])
def devices_list(request: Any) -> Response:
    """
    List all devices for React frontend with search and pagination
    Requires staff authentication
    
    Query Parameters:
    - search: Search term (device_serial, user, customer name, etc.)
    - page: Page number (default: 1)
    - page_size: Items per page (default: 25, max: 100)
    """
    search = request.GET.get('search', '').strip()
    try:
        page = int(request.GET.get('page', 1))
        page_size = min(int(request.GET.get('page_size', 25)), 100)  # Max 100 per page
    except (ValueError, TypeError):
        return Response({"error": "Invalid page or page_size parameter. Must be integers."}, status=status.HTTP_400_BAD_REQUEST)
    
    # Optimize query: only fetch related data we need (including audit fields)
    devices = Device.objects.select_related('user', 'created_by', 'updated_by').all().order_by("-provisioned_at")

    # Apply search filter
    if search:
        devices = devices.filter(
            Q(device_serial__icontains=search) |
            Q(user__username__icontains=search) |
            Q(config_version__icontains=search)
        )
    
    # Get total count before pagination (only count filtered results)
    total_count = devices.count()
    
    # Apply pagination
    offset = (page - 1) * page_size
    paginated_devices = devices[offset:offset + page_size]
    
    # Format device data
    data = []
    for device in paginated_devices:
        data.append({
            "id": device.id,
            "device_serial": device.device_serial,
            "hw_id": device.hw_id,
            "model": device.model,
            "provisioned_at": device.provisioned_at.isoformat(),
            "config_version": device.config_version,
            "user": device.user.username if device.user else None,
            "is_online": device.is_online(),
            "last_heartbeat": device.last_heartbeat.isoformat() if device.last_heartbeat else None,
            "logs_enabled": device.logs_enabled,
            "pending_config_update": device.pending_config_update,
            "config_ack_ver": device.config_ack_ver,
            "config_downloaded_at": device.config_downloaded_at.isoformat() if device.config_downloaded_at else None,
            "config_acked_at": device.config_acked_at.isoformat() if device.config_acked_at else None,
            "created_by_username": device.created_by.username if device.created_by else None,
            "created_at": device.provisioned_at.isoformat(),
            "updated_by_username": device.updated_by.username if device.updated_by else None,
            "updated_at": device.updated_at.isoformat() if device.updated_at else None,
        })
    
    # Return paginated response
    total_pages = (total_count + page_size - 1) // page_size
    return Response({
        'count': total_count,
        'total_pages': total_pages,
        'current_page': page,
        'page_size': page_size,
        'has_next': page < total_pages,
        'has_previous': page > 1,
        'next_page': page + 1 if page < total_pages else None,
        'previous_page': page - 1 if page > 1 else None,
        'results': data
    })


@api_view(["GET"])
@permission_classes([IsStaffUser])
def config_get(request: Any) -> Response:
    """
    Get gateway configuration for React frontend.
    Returns 200 with {} when no configuration exists so the browser
    does not log a 404 network error. The frontend checks data?.configId
    and switches to global mode when the response is empty.
    Requires staff authentication.
    """
    config = GatewayConfig.objects.order_by("-updated_at").first()
    if not config:
        return Response({})

    return Response(GatewayConfigSerializer(config).data)


@api_view(["GET"])
@permission_classes([IsStaffUser])
@cache_page(60)  # Cache for 60 seconds
def telemetry_all(request: Any) -> Response:
    """
    Get all telemetry data for React frontend
    Requires staff authentication
    Optimized with select_related for foreign key lookups
    Cached for 60 seconds to reduce database load
    """
    try:
        limit = int(request.GET.get("limit", 100))
    except (ValueError, TypeError):
        return Response({"error": "Invalid limit parameter. Must be an integer."}, status=status.HTTP_400_BAD_REQUEST)
    
    telemetry = TelemetryData.objects.select_related('device').order_by("-timestamp")[:limit]
    return Response(TelemetryDataSerializer(telemetry, many=True).data)


@api_view(["GET"])
@permission_classes([IsStaffUser])
def alerts_list(request: Any) -> Response:
    """
    Get system alerts for React frontend
    Requires staff authentication
    Optimized with select_related to reduce database queries
    """
    # For now, generate mock alerts based on telemetry data
    alerts = []
    recent_telemetry = TelemetryData.objects.select_related('device').filter(timestamp__gte=timezone.now() - timedelta(hours=1))
    
    # Get all devices at once to avoid N+1 queries
    devices = Device.objects.all()
    
    # Build a map of device to latest telemetry "
    device_latest_telemetry = {}
    for telemetry in recent_telemetry.order_by('-timestamp'):
        if telemetry.device_id not in device_latest_telemetry:
            device_latest_telemetry[telemetry.device_id] = telemetry
    
    # Check for offline devices
    for device in devices:
        last_heartbeat = device_latest_telemetry.get(device.id)
        if not last_heartbeat or (timezone.now() - last_heartbeat.timestamp).total_seconds() > 300:  # 5 minutes
            alerts.append({
                "id": f"device_offline_{device.device_serial}",
                "type": "device_offline",
                "severity": "warning",
                "message": f"Device {device.device_serial} appears to be offline",
                "device_id": device.device_serial,
                "timestamp": timezone.now().isoformat(),
                "resolved": False
            })
    
    # Check for abnormal readings
    for telemetry in recent_telemetry:
        if telemetry.data_type == "voltage" and telemetry.value < 10:  # Low voltage alert
            alerts.append({
                "id": f"low_voltage_{telemetry.id}",
                "type": "low_voltage",
                "severity": "critical",
                "message": f"Low voltage detected: {telemetry.value}V on device {telemetry.device.device_serial}",
                "device_id": telemetry.device.device_serial,
                "timestamp": telemetry.timestamp.isoformat(),
                "resolved": False
            })
        elif telemetry.data_type == "temperature" and telemetry.value > 80:  # High temperature alert
            alerts.append({
                "id": f"high_temp_{telemetry.id}",
                "type": "high_temperature",
                "severity": "warning",
                "message": f"High temperature detected: {telemetry.value}°C on device {telemetry.device.device_serial}",
                "device_id": telemetry.device.device_serial,
                "timestamp": telemetry.timestamp.isoformat(),
                "resolved": False
            })
    
    return Response(alerts)


@api_view(["GET"])
@permission_classes([IsStaffUser])
@cache_page(30)  # Cache for 30 seconds since it's for monitoring
def system_health(request: Any) -> Response:
    """
    Get system health metrics for React frontend
    Requires staff authentication
    Cached for 30 seconds to balance freshness and performance
    
    Performance optimized: Uses database-level aggregations
    """
    now = timezone.now()
    one_hour_ago = now - timedelta(hours=1)
    five_minutes_ago = now - timedelta(minutes=5)
    
    # Batch count queries using aggregate (more efficient than separate count() calls)
    stats = Device.objects.aggregate(total_devices=Count('id'))
    telemetry_stats = TelemetryData.objects.aggregate(
        total_telemetry=Count('id'),
        active_devices=Count('device_id', distinct=True, filter=Q(timestamp__gte=one_hour_ago)),
        has_recent=Count('id', filter=Q(timestamp__gte=five_minutes_ago))
    )
    
    # Get earliest timestamp for uptime calculation (only fetch the timestamp field)
    first_telemetry = TelemetryData.objects.order_by("timestamp").values('timestamp').first()
    uptime_seconds = 0
    if first_telemetry:
        uptime_seconds = (now - first_telemetry['timestamp']).total_seconds()
    
    # Database connection status
    db_status = "healthy"
    
    # MQTT broker status (simplified - assume healthy if we have recent data)
    mqtt_status = "healthy" if telemetry_stats['has_recent'] > 0 else "warning"
    active_devices = telemetry_stats['active_devices'] or 0
    
    return Response({
        "total_devices": stats['total_devices'] or 0,
        "active_devices": active_devices,
        "total_telemetry_points": telemetry_stats['total_telemetry'] or 0,
        "uptime_seconds": uptime_seconds,
        "database_status": db_status,
        "mqtt_status": mqtt_status,
        "overall_health": "healthy" if active_devices > 0 else "warning"
    })


@api_view(["GET"])
@permission_classes([IsStaffUser])
@cache_page(60)  # Cache for 60 seconds  
def kpis(request: Any) -> Response:
    """
    Get key performance indicators for React frontend
    Requires staff authentication
    Cached for 60 seconds to reduce calculation overhead
    
    Performance optimized: Uses database-level aggregations instead of Python calculations
    """
    cutoff_time = timezone.now() - timedelta(hours=24)
    
    # Use database aggregations for efficiency (single query for counts)
    base_stats = TelemetryData.objects.filter(
        timestamp__gte=cutoff_time
    ).aggregate(
        data_points=Count('id'),
        active_devices=Count('device_id', distinct=True)
    )
    
    # Aggregate by data_type in a single query
    type_aggregates = TelemetryData.objects.filter(
        timestamp__gte=cutoff_time
    ).values('data_type').annotate(
        avg_value=Avg('value'),
        sum_value=Sum('value'),
        count=Count('id')
    )
    
    # Build lookup for easy access
    aggregates = {item['data_type']: item for item in type_aggregates}
    
    voltage_data = aggregates.get('voltage', {})
    current_data = aggregates.get('current', {})
    power_data = aggregates.get('power', {})
    
    avg_voltage = voltage_data.get('avg_value') or 0
    avg_current = current_data.get('avg_value') or 0
    total_power = power_data.get('sum_value') or 0
    
    # Calculate efficiency (simplified)
    efficiency = 0
    if avg_voltage > 0 and avg_current > 0:
        efficiency = min(100, (avg_voltage * avg_current) / 100)
    
    kpis = {
        "total_energy_generated": (total_power * 24 / 1000) if total_power else 0,  # kWh approximation
        "average_voltage": round(avg_voltage, 2),
        "average_current": round(avg_current, 2),
        "system_efficiency": round(efficiency, 2),
        "data_points_last_24h": base_stats['data_points'] or 0,
        "active_devices_24h": base_stats['active_devices'] or 0
    }
    
    return Response(kpis)


@api_view(['POST'])
@permission_classes([AllowAny])
@ratelimit(key='ip', rate='5/m', block=True)
def register_user(request):
    """
    Register a new user
    Rate limited: 5 registration attempts per minute per IP
    """
    username = request.data.get('username')
    email = request.data.get('email')
    password = request.data.get('password')
    first_name = request.data.get('first_name', '')
    last_name = request.data.get('last_name', '')

    if not username or not email or not password:
        return Response(
            {'error': 'Username, email, and password are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if User.objects.filter(username=username).exists():
        return Response(
            {'error': 'Username already exists'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if User.objects.filter(email=email).exists():
        return Response(
            {'error': 'Email already exists'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name
        )

        refresh = RefreshToken.for_user(user)
        return Response({
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
            },
            'tokens': {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )


@api_view(['POST'])
@permission_classes([AllowAny])
@ratelimit(key='ip', rate='5/m', block=True)
def login_user(request):
    """
    Login user and return JWT tokens
    Rate limited: 5 login attempts per minute per IP
    """
    username = request.data.get('username')
    password = request.data.get('password')

    if not username or not password:
        return Response(
            {'error': 'Username and password are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    user = authenticate(username=username, password=password)

    if user is None:
        return Response(
            {'error': 'Invalid credentials'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    refresh = RefreshToken.for_user(user)
    return Response({
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'is_staff': user.is_staff,
            'is_superuser': user.is_superuser,
        },
        'tokens': {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_user(request):
    """
    Logout user by blacklisting refresh token
    """
    try:
        refresh_token = request.data.get('refresh_token')
        if refresh_token:
            token = RefreshToken(refresh_token)
            token.blacklist()
        return Response({'message': 'Successfully logged out'})
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_current_user(request):
    """
    Get current authenticated user information
    """
    user = request.user
    profile, created = UserProfile.objects.get_or_create(user=user)
    return Response({
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'mobile_number': profile.mobile_number,
        'address': profile.address,
        'role': profile.role,
        'is_staff': user.is_staff,
        'is_superuser': user.is_superuser,
        'date_joined': user.date_joined,
    })


@api_view(['GET'])
@permission_classes([IsStaffUser])
def users_list(request):
    """
    List all users with profiles, with optional search
    Requires staff authentication
    """
    search = request.GET.get('search', '').strip()
    users = User.objects.all().select_related('userprofile')
    
    if search:
        users = users.filter(
            Q(username__icontains=search) |
            Q(email__icontains=search) |
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(userprofile__mobile_number__icontains=search) |
            Q(userprofile__address__icontains=search)
        )
    
    data = []
    for user in users:
        profile = getattr(user, 'userprofile', None)
        data.append({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'mobile_number': profile.mobile_number if profile else None,
            'address': profile.address if profile else None,
            'role': profile.role if profile else UserProfile.Role.USER,
            'is_staff': user.is_staff,
            'is_superuser': user.is_superuser,
            'date_joined': user.date_joined.isoformat(),
        })
    return Response(data)


@api_view(['POST'])
@permission_classes([IsStaffUser])
def create_user(request):
    """
    Create a new user (staff only)
    Only superusers can create staff users
    """
    # Check if trying to create staff user
    is_staff = request.data.get('is_staff', False)
    if is_staff and not request.user.is_superuser:
        return Response(
            {'error': 'Only superusers can create staff users'},
            status=status.HTTP_403_FORBIDDEN
        )
    username = request.data.get('username')
    email = request.data.get('email')
    password = request.data.get('password')
    first_name = request.data.get('first_name', '')
    last_name = request.data.get('last_name', '')
    mobile_number = request.data.get('mobile_number', '')
    address = request.data.get('address', '')
    is_staff = request.data.get('is_staff', False)
    role = request.data.get('role', UserProfile.Role.USER)
    if role not in UserProfile.Role.values:
        role = UserProfile.Role.USER

    if not username or not email or not password:
        return Response(
            {'error': 'Username, email, and password are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if User.objects.filter(username=username).exists():
        return Response(
            {'error': 'Username already exists'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if User.objects.filter(email=email).exists():
        return Response(
            {'error': 'Email already exists'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name
        )
        
        # Set is_staff based on request
        user.is_staff = is_staff
        user.save()

        # Create profile
        UserProfile.objects.create(
            user=user,
            mobile_number=mobile_number,
            address=address,
            role=role,
        )

        return Response({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'mobile_number': mobile_number,
            'address': address,
            'role': role,
            'is_staff': user.is_staff,
            'is_superuser': user.is_superuser,
            'date_joined': user.date_joined.isoformat(),
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )


@api_view(['PUT'])
@permission_classes([IsStaffUser])
def update_user(request, user_id):
    """
    Update user and profile
    Requires staff authentication
    """
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Update user fields
    user.first_name = request.data.get('first_name', user.first_name)
    user.last_name = request.data.get('last_name', user.last_name)
    user.email = request.data.get('email', user.email)
    user.save()
    
    # Update profile
    profile, created = UserProfile.objects.get_or_create(user=user)
    profile.mobile_number = request.data.get('mobile_number', profile.mobile_number)
    profile.address = request.data.get('address', profile.address)
    if 'role' in request.data and request.data['role'] in UserProfile.Role.values:
        profile.role = request.data['role']
    profile.save()

    return Response({
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'mobile_number': profile.mobile_number,
        'address': profile.address,
        'role': profile.role,
        'date_joined': user.date_joined.isoformat(),
    })


@api_view(['DELETE'])
@permission_classes([IsStaffUser])
def delete_user(request, user_id):
    """
    Delete a user and their profile (staff only)
    """
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Prevent deleting self
    if user == request.user:
        return Response({'error': 'Cannot delete your own account'}, status=status.HTTP_400_BAD_REQUEST)
    
    user.delete()
    return Response({'message': 'User deleted successfully'})


@api_view(['GET'])
@permission_classes([IsStaffUser])
def get_user_devices(request, user_id):
    """
    Get all devices assigned to a specific user
    Requires staff authentication
    """
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Get devices assigned to this user
    devices = Device.objects.filter(user=user)
    
    device_list = []
    for device in devices:
        device_list.append({
            'id': device.id,
            'device_serial': device.device_serial,
            'hw_id': device.hw_id,
            'model': device.model,
            'provisioned_at': device.provisioned_at.isoformat() if device.provisioned_at else None,
            'config_version': device.config_version,
            'is_online': device.is_online(),
            'last_heartbeat': device.last_heartbeat.isoformat() if device.last_heartbeat else None,
            'logs_enabled': device.logs_enabled,
        })
    
    return Response(device_list)


# ========== PROFILE MANAGEMENT ENDPOINTS ==========

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_profile(request):
    """
    Get the current logged-in user's profile
    """
    user = request.user
    
    profile = getattr(user, 'userprofile', None)

    return Response({
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'mobile_number': profile.mobile_number if profile else None,
        'address': profile.address if profile else None,
        'role': profile.role if profile else UserProfile.Role.USER,
        'is_staff': user.is_staff,
        'is_superuser': user.is_superuser,
        'date_joined': user.date_joined.isoformat(),
    })


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_profile(request):
    """
    Update the current logged-in user's profile
    """
    user = request.user
    
    # Update user fields
    if 'first_name' in request.data:
        user.first_name = request.data['first_name']
    if 'last_name' in request.data:
        user.last_name = request.data['last_name']
    if 'email' in request.data:
        # Check if email is already taken by another user
        new_email = request.data['email']
        if User.objects.filter(email=new_email).exclude(id=user.id).exists():
            return Response({'error': 'Email already in use'}, status=status.HTTP_400_BAD_REQUEST)
        user.email = new_email
    
    user.save()
    
    # Update profile fields
    profile, created = UserProfile.objects.get_or_create(user=user)
    if 'mobile_number' in request.data:
        profile.mobile_number = request.data['mobile_number']
    if 'address' in request.data:
        profile.address = request.data['address']
    profile.save()
    
    return Response({
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'mobile_number': profile.mobile_number,
        'address': profile.address,
        'role': profile.role,
        'is_staff': user.is_staff,
        'is_superuser': user.is_superuser,
        'date_joined': user.date_joined.isoformat(),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    """
    Change the current logged-in user's password
    """
    user = request.user
    
    current_password = request.data.get('current_password')
    new_password = request.data.get('new_password')
    
    if not current_password or not new_password:
        return Response(
            {'error': 'Current password and new password are required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Verify current password
    if not user.check_password(current_password):
        return Response({'error': 'Current password is incorrect'}, status=status.HTTP_400_BAD_REQUEST)
    
    # Validate new password length
    if len(new_password) < 8:
        return Response(
            {'error': 'New password must be at least 8 characters long'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Set new password
    user.set_password(new_password)
    user.save()
    
    return Response({'message': 'Password changed successfully'})




@api_view(['GET'])
@permission_classes([IsStaffUser])
def presets_list(request):
    from django.db.models import Count
    configs = GatewayConfig.objects.select_related('created_by', 'updated_by').annotate(
        slaves_count=Count('slaves')
    ).order_by('-updated_at')
    data = []
    for config in configs:
        # Format parity for display
        parity_display = {0: 'None', 1: 'Odd', 2: 'Even'}.get(config.parity, 'Unknown')

        data.append({
            'id': config.id,
            'config_id': config.config_id,
            'name': config.name or config.config_id,
            'description': f'Config with {config.slaves_count} slaves',
            'version': config.version,
            'updated_at': config.updated_at.isoformat(),
            'gateway_configuration': {
                'general_settings': {
                    'config_id': config.config_id,
                    'schema_version': config.config_schema_ver,
                    'last_updated': config.updated_at.strftime('%m/%d/%Y, %I:%M:%S %p'),
                },
                'uart_configuration': {
                    'baud_rate': config.baud_rate,
                    'data_bits': config.data_bits,
                    'stop_bits': config.stop_bits,
                    'parity': parity_display,
                }
            },
            'slaves_count': config.slaves_count,
        })
    return Response(data)


@api_view(['POST'])
@permission_classes([IsStaffUser])
def create_preset(request):
    name = request.data.get('name', '')
    description = request.data.get('description', '')
    baud_rate = request.data.get('baud_rate', 9600)
    data_bits = request.data.get('data_bits', 8)
    stop_bits = request.data.get('stop_bits', 1)
    parity = request.data.get('parity', 0)

    # Generate unique random config_id
    existing_configs = set(GatewayConfig.objects.all().values_list('config_id', flat=True))

    while True:
        # Generate a random 8-character alphanumeric config ID
        config_id = ''.join(secrets.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(8))
        if config_id not in existing_configs:
            break

    config = GatewayConfig.objects.create(
        config_id=config_id,
        name=name,
        config_schema_ver=1,
        baud_rate=baud_rate,
        data_bits=data_bits,
        stop_bits=stop_bits,
        parity=parity,
    )

    # Format parity for display
    parity_display = {0: 'None', 1: 'Odd', 2: 'Even'}.get(config.parity, 'Unknown')

    return Response({
        'id': config.id,
        'config_id': config.config_id,
        'name': config.name or config.config_id,
        'description': description,
        'gateway_configuration': {
            'general_settings': {
                'config_id': config.config_id,
                'schema_version': config.config_schema_ver,
                'last_updated': config.updated_at.strftime('%m/%d/%Y, %I:%M:%S %p'),
            },
            'uart_configuration': {
                'baud_rate': config.baud_rate,
                'data_bits': config.data_bits,
                'stop_bits': config.stop_bits,
                'parity': parity_display,
            }
        },
        'slaves_count': 0,
    }, status=status.HTTP_201_CREATED)


@api_view(['PUT'])
@permission_classes([IsStaffUser])
def update_preset(request, preset_id):
    try:
        config = GatewayConfig.objects.get(id=preset_id)
    except GatewayConfig.DoesNotExist:
        return Response({'error': 'Preset not found'}, status=status.HTTP_404_NOT_FOUND)

    old_config_id = config.config_id
    config.name = request.data.get('name', config.name)
    config.config_id = request.data.get('config_id', config.config_id)
    config.baud_rate = request.data.get('baud_rate', config.baud_rate)
    config.data_bits = request.data.get('data_bits', config.data_bits)
    config.stop_bits = request.data.get('stop_bits', config.stop_bits)
    config.parity = request.data.get('parity', config.parity)
    config.save()

    # Mark all devices using this config as needing a config update
    Device.objects.filter(config_version=config.config_id).update(pending_config_update=True)
    # Also handle case where config_id itself changed
    if old_config_id != config.config_id:
        Device.objects.filter(config_version=old_config_id).update(pending_config_update=True)

    slaves = SlaveDevice.objects.filter(gateway_config=config).count()

    # Format parity for display
    parity_display = {0: 'None', 1: 'Odd', 2: 'Even'}.get(config.parity, 'Unknown')

    return Response({
        'id': config.id,
        'config_id': config.config_id,
        'name': config.name or config.config_id,
        'description': f'Config with {slaves} slaves',
        'gateway_configuration': {
            'general_settings': {
                'config_id': config.config_id,
                'schema_version': config.config_schema_ver,
                'last_updated': config.updated_at.strftime('%m/%d/%Y, %I:%M:%S %p'),
            },
            'uart_configuration': {
                'baud_rate': config.baud_rate,
                'data_bits': config.data_bits,
                'stop_bits': config.stop_bits,
                'parity': parity_display,
            }
        },
        'slaves_count': slaves,
    })


@api_view(['DELETE'])
@permission_classes([IsStaffUser])
def delete_preset(request, preset_id):
    try:
        config = GatewayConfig.objects.get(id=preset_id)
    except GatewayConfig.DoesNotExist:
        return Response({'error': 'Preset not found'}, status=status.HTTP_404_NOT_FOUND)

    config.delete()
    return Response({'message': 'Preset deleted'})




@api_view(['POST'])
@permission_classes([IsStaffUser])
def create_device(request):
    serializer = DeviceSerializer(data=request.data)
    if serializer.is_valid():
        device = serializer.save()
        # Set audit fields
        set_audit_fields(device, request)
        device.save()
        # Re-serialize to include audit fields
        response_serializer = DeviceSerializer(device)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PUT'])
@permission_classes([IsStaffUser])
def update_device(request, device_id):
    try:
        device = Device.objects.get(id=device_id)
    except Device.DoesNotExist:
        return Response({'error': 'Device not found'}, status=status.HTTP_404_NOT_FOUND)

    serializer = DeviceSerializer(device, data=request.data, partial=True)
    if serializer.is_valid():
        old_config_version = device.config_version
        device = serializer.save()
        # Set audit fields
        set_audit_fields(device, request)
        # Set pending_config_update when preset assignment changes
        if old_config_version != device.config_version:
            device.pending_config_update = True
            logger.info(f"Device {device.device_serial} config changed from {old_config_version} to {device.config_version} — config update flagged")
        device.save()
        # Re-serialize to include audit fields
        response_serializer = DeviceSerializer(device)
        return Response(response_serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsStaffUser])
def reboot_device(request, device_id):
    """
    Trigger a device reboot by setting pending_reboot flag.
    The next heartbeat will return reboot command and clear the flag.
    Requires staff authentication.
    """
    try:
        device = Device.objects.get(id=device_id)
    except Device.DoesNotExist:
        return Response({'error': 'Device not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Set reboot flag
    device.pending_reboot = True
    device.save(update_fields=['pending_reboot'])
    
    logger.info(f"Reboot command queued for device {device.device_serial} by user {request.user}")
    
    return Response({
        'message': f'Reboot command queued for device {device.device_serial}',
        'device_id': device.id,
        'device_serial': device.device_serial,
        'pending_reboot': True
    })


@api_view(['POST'])
@permission_classes([IsStaffUser])
def hard_reset_device(request, device_id):
    """
    Trigger a device hard reset by setting pending_hard_reset flag.
    The next heartbeat will return hardReset command and clear the flag.
    Requires staff authentication.
    """
    try:
        device = Device.objects.get(id=device_id)
    except Device.DoesNotExist:
        return Response({'error': 'Device not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Set hard reset flag
    device.pending_hard_reset = True
    device.save(update_fields=['pending_hard_reset'])
    
    logger.info(f"Hard reset command queued for device {device.device_serial} by user {request.user}")
    
    return Response({
        'message': f'Hard reset command queued for device {device.device_serial}',
        'device_id': device.id,
        'device_serial': device.device_serial,
        'pending_hard_reset': True
    })


@api_view(['POST'])
@permission_classes([IsStaffUser])
def rollback_device(request, device_id):
    """
    Trigger a firmware rollback by setting pending_rollback flag.
    The device must already have the previous firmware stored locally.
    The next heartbeat will return updateFirmware: 2 command and clear the flag.
    Requires staff authentication.
    """
    try:
        device = Device.objects.get(id=device_id)
    except Device.DoesNotExist:
        return Response({'error': 'Device not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Set rollback flag
    device.pending_rollback = True
    device.save(update_fields=['pending_rollback'])
    
    logger.info(f"Rollback command queued for device {device.device_serial} by user {request.user}")
    
    return Response({
        'message': f'Rollback command queued for device {device.device_serial}',
        'device_id': device.id,
        'device_serial': device.device_serial,
        'pending_rollback': True,
        'info': 'Device will receive updateFirmware: 2 flag on next heartbeat'
    })


@api_view(['DELETE'])
@permission_classes([IsStaffUser])
def delete_device(request, device_id):
    try:
        device = Device.objects.get(id=device_id)
        device_serial = device.device_serial
        
        # Delete device (telemetry will cascade delete automatically)
        device.delete()
        
        logger.info(f"Device {device_serial} deleted successfully by user {request.user}")
        return Response({'message': 'Device deleted successfully'})
        
    except Device.DoesNotExist:
        logger.error(f"Device with ID {device_id} not found")
        return Response({'error': 'Device not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Error deleting device {device_id}: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsStaffUser])
def device_logs_retrieve(request, device_id):
    """
    Retrieve device logs for UI display.
    Requires staff authentication.
    """
    try:
        device = Device.objects.get(id=device_id)
    except Device.DoesNotExist:
        return Response({'error': 'Device not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Get logs with pagination
    limit = int(request.GET.get('limit', 100))
    offset = int(request.GET.get('offset', 0))
    
    logs = DeviceLog.objects.filter(device=device)[offset:offset+limit]
    total_count = DeviceLog.objects.filter(device=device).count()
    
    logs_data = [{
        'id': log.id,
        'timestamp': log.timestamp.isoformat(),
        'level': log.log_level,
        'message': log.message,
        'metadata': log.metadata
    } for log in logs]
    
    return Response({
        'logs': logs_data,
        'total': total_count,
        'limit': limit,
        'offset': offset
    })


@api_view(['POST'])
@permission_classes([IsStaffUser])
def toggle_device_logs(request, device_id):
    """
    Toggle logs_enabled flag for a device.
    Requires staff authentication.
    """
    try:
        device = Device.objects.get(id=device_id)
    except Device.DoesNotExist:
        return Response({'error': 'Device not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Toggle or set logs_enabled
    if 'enabled' in request.data:
        device.logs_enabled = request.data['enabled']
    else:
        device.logs_enabled = not device.logs_enabled
    
    device.save(update_fields=['logs_enabled'])
    
    logger.info(f"Device {device.device_serial} logs {'enabled' if device.logs_enabled else 'disabled'} by user {request.user}")
    
    return Response({
        'message': f'Device logs {"enabled" if device.logs_enabled else "disabled"}',
        'device_id': device.id,
        'device_serial': device.device_serial,
        'logs_enabled': device.logs_enabled
    })


@api_view(['POST', 'OPTIONS'])
@permission_classes([IsStaffUser])
@ratelimit(key='user', rate='100/h')
def delete_devices_bulk(request):
    """
    Delete multiple devices at once
    
    Request body:
    {
        "device_ids": [1, 2, 3, ...]  // Required: list of device IDs to delete
    }
    
    Response:
    {
        "message": "X devices deleted successfully",
        "deleted_count": X,
        "deleted_devices": [
            {"id": 1, "serial": "DEVICE001"},
            ...
        ],
        "failed_deletions": [
            {"id": 999, "error": "Device not found"}
        ]
    }
    """
    try:
        device_ids = request.data.get('device_ids', [])
        
        if not device_ids:
            return Response(
                {'error': 'device_ids list is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not isinstance(device_ids, list):
            return Response(
                {'error': 'device_ids must be a list'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if len(device_ids) == 0:
            return Response(
                {'error': 'device_ids list cannot be empty'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Limit bulk delete to 500 devices at a time for safety
        if len(device_ids) > 500:
            return Response(
                {'error': 'Cannot delete more than 500 devices at once'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate all device_ids are integers
        invalid_ids = []
        valid_ids = []
        for device_id in device_ids:
            if isinstance(device_id, int):
                valid_ids.append(device_id)
            else:
                invalid_ids.append(device_id)
        
        deleted_devices = []
        failed_deletions = []
        
        # Add invalid ID errors
        for device_id in invalid_ids:
            failed_deletions.append({
                'id': device_id,
                'error': 'Invalid device ID format (must be integer)'
            })
        
        # Get all devices that exist for deletion
        if valid_ids:
            existing_devices = Device.objects.filter(id__in=valid_ids)
            
            # Get serials before deletion
            device_map = {}
            for device in existing_devices:
                device_map[device.id] = device.device_serial
            
            # Get IDs that don't exist
            existing_ids = set(existing_devices.values_list('id', flat=True))
            missing_ids = set(valid_ids) - existing_ids
            
            # Add missing device errors
            for device_id in missing_ids:
                failed_deletions.append({
                    'id': device_id,
                    'error': 'Device not found'
                })
            
            # Delete all existing devices in bulk (faster than loop)
            delete_count = existing_devices.count()
            existing_devices.delete()
            
            # Record deleted devices
            for device_id, device_serial in device_map.items():
                if device_id not in missing_ids:
                    deleted_devices.append({
                        'id': device_id,
                        'serial': device_serial
                    })
            
            # Log bulk deletion
            logger.info(f"Bulk delete completed: {delete_count} devices deleted by user {request.user}")
        
        # Prepare response
        response_data = {
            'message': f'{len(deleted_devices)} devices deleted successfully',
            'deleted_count': len(deleted_devices),
            'deleted_devices': deleted_devices,
        }
        
        # Only include failed_deletions if there are any
        if failed_deletions:
            response_data['failed_deletions'] = failed_deletions
            response_data['failed_count'] = len(failed_deletions)
        
        # Return appropriate status code
        if failed_deletions and not deleted_devices:
            # All deletions failed
            return Response(response_data, status=status.HTTP_400_BAD_REQUEST)
        else:
            # At least some deletions succeeded
            return Response(response_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error in bulk device deletion: {str(e)}")
        return Response(
            {'error': f'Bulk deletion error: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def _register_to_dict(reg):
    """Serialize a RegisterMapping instance to a dict for API responses."""
    return {
        'id': reg.id,
        'label': reg.label,
        'address': reg.address,
        'num_registers': reg.num_registers,
        'function_code': reg.function_code,
        'register_type': reg.register_type,
        'data_type': reg.data_type,
        'byte_order': reg.byte_order,
        'word_order': reg.word_order,
        'access_mode': reg.access_mode,
        'scale_factor': reg.scale_factor,
        'offset': reg.offset,
        'unit': reg.unit,
        'decimal_places': reg.decimal_places,
        'category': reg.category,
        'high_alarm_threshold': reg.high_alarm_threshold,
        'low_alarm_threshold': reg.low_alarm_threshold,
        'description': reg.description,
        'enabled': reg.enabled,
    }


@api_view(['GET'])
@permission_classes([IsStaffUser])
def global_slaves_list(request):
    """
    Get all slaves across all gateway configurations.
    Requires staff authentication.
    """
    slaves = SlaveDevice.objects.select_related('gateway_config').prefetch_related('registers').all()
    data = []
    for slave in slaves:
        cfg = slave.gateway_config
        data.append({
            'id': slave.id,
            'slave_id': slave.slave_id,
            'device_name': slave.device_name,
            'polling_interval_ms': slave.polling_interval_ms,
            'timeout_ms': slave.timeout_ms,
            'priority': slave.priority,
            'enabled': slave.enabled,
            'config_id': cfg.id if cfg else None,
            'config_name': (cfg.name or cfg.config_id) if cfg else 'global',
            'registers': [_register_to_dict(reg) for reg in slave.registers.all()],
        })
    return Response(data)


@api_view(['POST'])
@permission_classes([IsStaffUser])
def global_slave_create(request):
    """
    Create a new slave device. Requires config_id (DB integer id) in the request body.
    Requires staff authentication.
    """
    # config_id is optional now — allow creating global (unattached) slaves
    config_id = request.data.get('config_id')
    config = None
    if config_id:
        try:
            config = GatewayConfig.objects.get(id=config_id)
        except GatewayConfig.DoesNotExist:
            return Response({'error': 'Configuration not found'}, status=status.HTTP_404_NOT_FOUND)

    slave_id = request.data.get('slave_id')
    device_name = request.data.get('device_name')
    polling_interval_ms = request.data.get('polling_interval_ms', 5000)
    timeout_ms = request.data.get('timeout_ms', 1000)
    priority = request.data.get('priority', 1)
    enabled = request.data.get('enabled', True)
    registers_data = request.data.get('registers', [])

    if not slave_id or not device_name:
        return Response({'error': 'slave_id and device_name are required'}, status=status.HTTP_400_BAD_REQUEST)

    # If config provided, enforce uniqueness per-config. Otherwise ensure global slave_id uniqueness
    if config:
        if SlaveDevice.objects.filter(gateway_config=config, slave_id=slave_id).exists():
            return Response({'error': 'Slave ID already exists for this configuration'}, status=status.HTTP_400_BAD_REQUEST)
    else:
        if SlaveDevice.objects.filter(gateway_config__isnull=True, slave_id=slave_id).exists():
            return Response({'error': 'Global Slave ID already exists'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        slave = SlaveDevice.objects.create(
            gateway_config=config,
            slave_id=slave_id,
            device_name=device_name,
            polling_interval_ms=polling_interval_ms,
            timeout_ms=timeout_ms,
            priority=priority,
            enabled=enabled,
        )

        registers = []
        for reg_data in registers_data:
            register = RegisterMapping.objects.create(
                slave=slave,
                label=reg_data.get('label', ''),
                address=reg_data.get('address', 0),
                num_registers=reg_data.get('num_registers', 1),
                function_code=reg_data.get('function_code', 3),
                register_type=reg_data.get('register_type', 3),
                data_type=reg_data.get('data_type', 0),
                byte_order=reg_data.get('byte_order', 0),
                word_order=reg_data.get('word_order', 0),
                access_mode=reg_data.get('access_mode', 0),
                scale_factor=reg_data.get('scale_factor', 1.0),
                offset=reg_data.get('offset', 0.0),
                unit=reg_data.get('unit') or None,
                decimal_places=reg_data.get('decimal_places', 2),
                category=reg_data.get('category') or None,
                high_alarm_threshold=reg_data.get('high_alarm_threshold'),
                low_alarm_threshold=reg_data.get('low_alarm_threshold'),
                description=reg_data.get('description') or None,
                enabled=reg_data.get('enabled', True),
            )
            registers.append(_register_to_dict(register))

        # Update parent GatewayConfig timestamp to trigger device config updates
        if config:
            GatewayConfig.objects.filter(pk=config.pk).update(updated_at=timezone.now(), version=F('version') + 1)
            Device.objects.filter(config_version=config.config_id).update(pending_config_update=True)

        return Response({
            'id': slave.id,
            'slave_id': slave.slave_id,
            'device_name': slave.device_name,
            'polling_interval_ms': slave.polling_interval_ms,
            'timeout_ms': slave.timeout_ms,
            'priority': slave.priority,
            'enabled': slave.enabled,
            'config_id': config.id if config else None,
            'config_name': (config.name or config.config_id) if config else 'global',
            'registers': registers,
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PUT'])
@permission_classes([IsStaffUser])
def global_slave_update(request, slave_pk):
    """
    Update a slave device by its DB primary key.
    Requires staff authentication.
    """
    try:
        slave = SlaveDevice.objects.select_related('gateway_config').get(id=slave_pk)
    except SlaveDevice.DoesNotExist:
        return Response({'error': 'Slave not found'}, status=status.HTTP_404_NOT_FOUND)

    slave.device_name = request.data.get('device_name', slave.device_name)
    slave.polling_interval_ms = request.data.get('polling_interval_ms', slave.polling_interval_ms)
    slave.timeout_ms = request.data.get('timeout_ms', slave.timeout_ms)
    slave.priority = request.data.get('priority', slave.priority)
    slave.enabled = request.data.get('enabled', slave.enabled)
    registers_data = request.data.get('registers', [])
    slave.save()

    RegisterMapping.objects.filter(slave=slave).delete()
    registers = []
    for reg_data in registers_data:
        register = RegisterMapping.objects.create(
            slave=slave,
            label=reg_data.get('label', ''),
            address=reg_data.get('address', 0),
            num_registers=reg_data.get('num_registers', 1),
            function_code=reg_data.get('function_code', 3),
            register_type=reg_data.get('register_type', 3),
            data_type=reg_data.get('data_type', 0),
            byte_order=reg_data.get('byte_order', 0),
            word_order=reg_data.get('word_order', 0),
            access_mode=reg_data.get('access_mode', 0),
            scale_factor=reg_data.get('scale_factor', 1.0),
            offset=reg_data.get('offset', 0.0),
            unit=reg_data.get('unit') or None,
            decimal_places=reg_data.get('decimal_places', 2),
            category=reg_data.get('category') or None,
            high_alarm_threshold=reg_data.get('high_alarm_threshold'),
            low_alarm_threshold=reg_data.get('low_alarm_threshold'),
            description=reg_data.get('description') or None,
            enabled=reg_data.get('enabled', True),
        )
        registers.append(_register_to_dict(register))

    # Update parent GatewayConfig timestamp to trigger device config updates
    config = slave.gateway_config
    if config:
        GatewayConfig.objects.filter(pk=config.pk).update(updated_at=timezone.now(), version=F('version') + 1)
        Device.objects.filter(config_version=config.config_id).update(pending_config_update=True)

    return Response({
        'id': slave.id,
        'slave_id': slave.slave_id,
        'device_name': slave.device_name,
        'polling_interval_ms': slave.polling_interval_ms,
        'timeout_ms': slave.timeout_ms,
        'priority': slave.priority,
        'enabled': slave.enabled,
        'config_id': config.id if config else None,
        'config_name': (config.name or config.config_id) if config else 'global',
        'registers': registers,
    })


@api_view(['DELETE'])
@permission_classes([IsStaffUser])
def global_slave_delete(request, slave_pk):
    """
    Delete a slave device by its DB primary key.
    Requires staff authentication.
    """
    try:
        slave = SlaveDevice.objects.select_related('gateway_config').get(id=slave_pk)
    except SlaveDevice.DoesNotExist:
        return Response({'error': 'Slave not found'}, status=status.HTTP_404_NOT_FOUND)

    # Update parent config before deleting slave
    config = slave.gateway_config
    if config:
        GatewayConfig.objects.filter(pk=config.pk).update(updated_at=timezone.now(), version=F('version') + 1)
        Device.objects.filter(config_version=config.config_id).update(pending_config_update=True)

    slave.delete()
    return Response({'message': 'Slave deleted successfully'})


@api_view(['GET'])
@permission_classes([IsStaffUser])
def slaves_list(request, config_id):
    """
    Get all slaves for a gateway configuration
    Requires staff authentication
    """
    try:
        config = GatewayConfig.objects.get(config_id=config_id)
    except GatewayConfig.DoesNotExist:
        return Response({'error': 'Configuration not found'}, status=status.HTTP_404_NOT_FOUND)

    slaves = SlaveDevice.objects.filter(gateway_config=config).prefetch_related('registers')
    data = []
    for slave in slaves:
        data.append({
            'id': slave.id,
            'slave_id': slave.slave_id,
            'device_name': slave.device_name,
            'polling_interval_ms': slave.polling_interval_ms,
            'timeout_ms': slave.timeout_ms,
            'priority': slave.priority,
            'enabled': slave.enabled,
            'registers': [_register_to_dict(reg) for reg in slave.registers.all()]
        })
    return Response(data)


@api_view(['POST'])
@permission_classes([IsStaffUser])
def create_slave(request, config_id):
    """
    Create a new slave device for a gateway configuration
    Requires staff authentication
    """
    try:
        config = GatewayConfig.objects.get(config_id=config_id)
    except GatewayConfig.DoesNotExist:
        return Response({'error': 'Configuration not found'}, status=status.HTTP_404_NOT_FOUND)

    slave_id = request.data.get('slave_id')
    device_name = request.data.get('device_name')
    polling_interval_ms = request.data.get('polling_interval_ms', 5000)
    timeout_ms = request.data.get('timeout_ms', 1000)
    priority = request.data.get('priority', 1)
    enabled = request.data.get('enabled', True)
    registers_data = request.data.get('registers', [])

    if not slave_id or not device_name:
        return Response({'error': 'slave_id and device_name are required'}, status=status.HTTP_400_BAD_REQUEST)

    # Check if slave_id already exists for this config
    if SlaveDevice.objects.filter(gateway_config=config, slave_id=slave_id).exists():
        return Response({'error': 'Slave ID already exists for this configuration'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        slave = SlaveDevice.objects.create(
            gateway_config=config,
            slave_id=slave_id,
            device_name=device_name,
            polling_interval_ms=polling_interval_ms,
            timeout_ms=timeout_ms,
            priority=priority,
            enabled=enabled
        )

        # Create register mappings
        registers = []
        for reg_data in registers_data:
            register = RegisterMapping.objects.create(
                slave=slave,
                label=reg_data.get('label', ''),
                address=reg_data.get('address', 0),
                num_registers=reg_data.get('num_registers', 1),
                function_code=reg_data.get('function_code', 3),
                register_type=reg_data.get('register_type', 3),
                data_type=reg_data.get('data_type', 0),
                byte_order=reg_data.get('byte_order', 0),
                word_order=reg_data.get('word_order', 0),
                access_mode=reg_data.get('access_mode', 0),
                scale_factor=reg_data.get('scale_factor', 1.0),
                offset=reg_data.get('offset', 0.0),
                unit=reg_data.get('unit') or None,
                decimal_places=reg_data.get('decimal_places', 2),
                category=reg_data.get('category') or None,
                high_alarm_threshold=reg_data.get('high_alarm_threshold'),
                low_alarm_threshold=reg_data.get('low_alarm_threshold'),
                description=reg_data.get('description') or None,
                enabled=reg_data.get('enabled', True)
            )
            registers.append(_register_to_dict(register))

        # Update parent GatewayConfig version and flag all devices using this config
        GatewayConfig.objects.filter(pk=config.pk).update(updated_at=timezone.now(), version=F('version') + 1)
        Device.objects.filter(config_version=config.config_id).update(pending_config_update=True)

        return Response({
            'id': slave.id,
            'slave_id': slave.slave_id,
            'device_name': slave.device_name,
            'polling_interval_ms': slave.polling_interval_ms,
            'timeout_ms': slave.timeout_ms,
            'priority': slave.priority,
            'enabled': slave.enabled,
            'registers': registers
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PUT'])
@permission_classes([IsStaffUser])
def update_slave(request, config_id, slave_id):
    """
    Update a slave device
    Requires staff authentication
    """
    try:
        config = GatewayConfig.objects.get(config_id=config_id)
        slave = SlaveDevice.objects.get(gateway_config=config, slave_id=slave_id)
    except GatewayConfig.DoesNotExist:
        return Response({'error': 'Configuration not found'}, status=status.HTTP_404_NOT_FOUND)
    except SlaveDevice.DoesNotExist:
        return Response({'error': 'Slave not found'}, status=status.HTTP_404_NOT_FOUND)

    slave.device_name = request.data.get('device_name', slave.device_name)
    slave.polling_interval_ms = request.data.get('polling_interval_ms', slave.polling_interval_ms)
    slave.timeout_ms = request.data.get('timeout_ms', slave.timeout_ms)
    slave.priority = request.data.get('priority', slave.priority)
    slave.enabled = request.data.get('enabled', slave.enabled)
    registers_data = request.data.get('registers', [])
    slave.save()

    # Update parent GatewayConfig version and flag all devices using this config
    GatewayConfig.objects.filter(pk=config.pk).update(updated_at=timezone.now(), version=F('version') + 1)
    Device.objects.filter(config_version=config.config_id).update(pending_config_update=True)

    # Update registers - delete existing and create new ones
    RegisterMapping.objects.filter(slave=slave).delete()
    registers = []
    for reg_data in registers_data:
        register = RegisterMapping.objects.create(
            slave=slave,
            label=reg_data.get('label', ''),
            address=reg_data.get('address', 0),
            num_registers=reg_data.get('num_registers', 1),
            function_code=reg_data.get('function_code', 3),
            register_type=reg_data.get('register_type', 3),
            data_type=reg_data.get('data_type', 0),
            byte_order=reg_data.get('byte_order', 0),
            word_order=reg_data.get('word_order', 0),
            access_mode=reg_data.get('access_mode', 0),
            scale_factor=reg_data.get('scale_factor', 1.0),
            offset=reg_data.get('offset', 0.0),
            unit=reg_data.get('unit') or None,
            decimal_places=reg_data.get('decimal_places', 2),
            category=reg_data.get('category') or None,
            high_alarm_threshold=reg_data.get('high_alarm_threshold'),
            low_alarm_threshold=reg_data.get('low_alarm_threshold'),
            description=reg_data.get('description') or None,
            enabled=reg_data.get('enabled', True)
        )
        registers.append(_register_to_dict(register))

    return Response({
        'id': slave.id,
        'slave_id': slave.slave_id,
        'device_name': slave.device_name,
        'polling_interval_ms': slave.polling_interval_ms,
        'timeout_ms': slave.timeout_ms,
        'priority': slave.priority,
        'enabled': slave.enabled,
        'registers': registers
    })


@api_view(['DELETE'])
@permission_classes([IsStaffUser])
def delete_slave(request, config_id, slave_id):
    """
    Delete a slave device
    Requires staff authentication
    """
    try:
        config = GatewayConfig.objects.get(config_id=config_id)
        slave = SlaveDevice.objects.get(gateway_config=config, slave_id=slave_id)
    except GatewayConfig.DoesNotExist:
        return Response({'error': 'Configuration not found'}, status=status.HTTP_404_NOT_FOUND)
    except SlaveDevice.DoesNotExist:
        return Response({'error': 'Slave not found'}, status=status.HTTP_404_NOT_FOUND)

    slave.delete()

    # Update parent GatewayConfig version and flag all devices using this config
    GatewayConfig.objects.filter(pk=config.pk).update(updated_at=timezone.now(), version=F('version') + 1)
    Device.objects.filter(config_version=config.config_id).update(pending_config_update=True)

    return Response({'message': 'Slave deleted successfully'})


@api_view(['POST'])
@permission_classes([IsStaffUser])
def detach_slave_from_preset(request, config_id, slave_id):
    """
    Detach a slave from a preset without deleting the slave (set gateway_config to NULL).
    Requires staff authentication.
    """
    try:
        config = GatewayConfig.objects.get(config_id=config_id)
    except GatewayConfig.DoesNotExist:
        return Response({'error': 'Configuration not found'}, status=status.HTTP_404_NOT_FOUND)

    try:
        slave = SlaveDevice.objects.get(gateway_config=config, slave_id=slave_id)
    except SlaveDevice.DoesNotExist:
        return Response({'error': 'Slave not found for this configuration'}, status=status.HTTP_404_NOT_FOUND)

    # Detach by setting gateway_config to None
    slave.gateway_config = None
    slave.save(update_fields=['gateway_config'])

    # Update parent GatewayConfig version and flag all devices using this config
    GatewayConfig.objects.filter(pk=config.pk).update(updated_at=timezone.now(), version=F('version') + 1)
    Device.objects.filter(config_version=config.config_id).update(pending_config_update=True)

    return Response({'message': 'Slave detached from preset', 'id': slave.id, 'slave_id': slave.slave_id})


@api_view(['POST'])
@permission_classes([IsStaffUser])
def add_slaves_to_preset(request, config_id):
    """
    Attach existing global slaves to a preset by setting their gateway_config FK.
    Expects JSON: { "slave_ids": [1,2,3] }
    Requires staff authentication.
    """
    try:
        config = GatewayConfig.objects.get(config_id=config_id)
    except GatewayConfig.DoesNotExist:
        return Response({'error': 'Configuration not found'}, status=status.HTTP_404_NOT_FOUND)

    slave_ids = request.data.get('slave_ids', [])
    if not isinstance(slave_ids, list):
        return Response({'error': 'slave_ids must be a list'}, status=status.HTTP_400_BAD_REQUEST)

    slaves = SlaveDevice.objects.filter(id__in=slave_ids)
    updated = []
    for slave in slaves:
        slave.gateway_config = config
        slave.save()
        updated.append({
            'id': slave.id,
            'slave_id': slave.slave_id,
            'device_name': slave.device_name,
            'polling_interval_ms': slave.polling_interval_ms,
            'timeout_ms': slave.timeout_ms,
            'priority': slave.priority,
            'enabled': slave.enabled,
            'registers': [_register_to_dict(reg) for reg in slave.registers.all()],
            'config_id': config.config_id,
            'config_name': config.name if hasattr(config, 'name') else None,
        })
    
    # Update parent GatewayConfig version and flag all devices using this config
    if updated:
        GatewayConfig.objects.filter(pk=config.pk).update(updated_at=timezone.now(), version=F('version') + 1)
        Device.objects.filter(config_version=config.config_id).update(pending_config_update=True)

    return Response({'updated': updated}, status=status.HTTP_200_OK)


# ============== Health Check Endpoint ==============

@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request: Any) -> Response:
    """
    Health check endpoint for load balancers and monitoring.
    Returns system health status including database connectivity.
    """
    health_status = {
        'status': 'healthy',
        'timestamp': timezone.now().isoformat(),
        'version': '1.0.0',
        'checks': {}
    }
    
    # Check database connectivity
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        health_status['checks']['database'] = {'status': 'up', 'latency_ms': None}
    except Exception as e:
        health_status['status'] = 'unhealthy'
        health_status['checks']['database'] = {'status': 'down', 'error': str(e)}
    
    # Check cache (if configured)
    try:
        from django.core.cache import cache
        cache.set('health_check', 'ok', 10)
        if cache.get('health_check') == 'ok':
            health_status['checks']['cache'] = {'status': 'up'}
        else:
            health_status['checks']['cache'] = {'status': 'degraded'}
    except Exception as e:
        health_status['checks']['cache'] = {'status': 'not_configured'}
    
    status_code = status.HTTP_200_OK if health_status['status'] == 'healthy' else status.HTTP_503_SERVICE_UNAVAILABLE
    return Response(health_status, status=status_code)


# ============== Alert CRUD Endpoints ==============

from .models import Alert
from .serializers import AlertSerializer


@api_view(['GET', 'POST'])
@permission_classes([IsStaffUser])
def alerts_crud(request: Any) -> Response:
    """
    GET: List all alerts with optional filtering
    POST: Create a new alert
    Requires staff authentication
    """
    if request.method == 'GET':
        # Filter parameters
        device_serial = request.GET.get('device')
        severity = request.GET.get('severity')
        alert_status = request.GET.get('status')
        try:
            limit = int(request.GET.get('limit', 100))
        except (ValueError, TypeError):
            return Response({"error": "Invalid limit parameter. Must be an integer."}, status=status.HTTP_400_BAD_REQUEST)
        
        queryset = Alert.objects.select_related('device', 'created_by', 'acknowledged_by', 'resolved_by').all()
        
        if device_serial:
            queryset = queryset.filter(device__device_serial=device_serial)
        if severity:
            queryset = queryset.filter(severity=severity)
        if alert_status:
            queryset = queryset.filter(status=alert_status)
        
        queryset = queryset[:limit]
        serializer = AlertSerializer(queryset, many=True)
        return Response(serializer.data)
    
    elif request.method == 'POST':
        serializer = AlertSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsStaffUser])
def alert_detail(request: Any, alert_id: int) -> Response:
    """
    GET: Retrieve a single alert
    PUT: Update an alert
    DELETE: Delete an alert
    Requires staff authentication
    """
    try:
        alert = Alert.objects.get(id=alert_id)
    except Alert.DoesNotExist:
        return Response({'error': 'Alert not found'}, status=status.HTTP_404_NOT_FOUND)
    
    if request.method == 'GET':
        serializer = AlertSerializer(alert)
        return Response(serializer.data)
    
    elif request.method == 'PUT':
        serializer = AlertSerializer(alert, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    elif request.method == 'DELETE':
        alert.delete()
        return Response({'message': 'Alert deleted'}, status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsStaffUser])
def alert_acknowledge(request: Any, alert_id: int) -> Response:
    """
    Acknowledge an alert
    Requires staff authentication
    """
    try:
        alert = Alert.objects.get(id=alert_id)
    except Alert.DoesNotExist:
        return Response({'error': 'Alert not found'}, status=status.HTTP_404_NOT_FOUND)
    
    alert.acknowledge(request.user)
    serializer = AlertSerializer(alert)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsStaffUser])
def alert_resolve(request: Any, alert_id: int) -> Response:
    """
    Resolve an alert
    Requires staff authentication
    """
    try:
        alert = Alert.objects.get(id=alert_id)
    except Alert.DoesNotExist:
        return Response({'error': 'Alert not found'}, status=status.HTTP_404_NOT_FOUND)
    
    alert.resolve(request.user)
    serializer = AlertSerializer(alert)
    return Response(serializer.data)


# ─── Solar Site endpoints ────────────────────────────────────────────────────
from .models import SolarSite
from .serializers import SolarSiteSerializer


@api_view(['GET', 'POST'])
@permission_classes([IsStaffUser])
def user_site(request: Any, user_id: int) -> Response:
    """
    GET  — returns the solar site for the user's primary device, or null if none exists.
    POST — creates a new solar site linked to the user's primary device.
    Requires staff authentication.
    """
    device = Device.objects.filter(user_id=user_id).first()
    if not device:
        return Response({'error': 'No device assigned to this user'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        site = SolarSite.objects.filter(device_id=device.id).first()
        if not site:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(SolarSiteSerializer(site).data)

    # POST — create
    if SolarSite.objects.filter(device_id=device.id).exists():
        return Response(
            {'error': 'Site already exists — use PUT /users/{id}/site/update/ to edit'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    serializer = SolarSiteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    serializer.save(device=device)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['PUT'])
@permission_classes([IsStaffUser])
def user_site_update(request: Any, user_id: int) -> Response:
    """
    Update the solar site for a user's primary device.
    Requires staff authentication.
    """
    device = Device.objects.filter(user_id=user_id).first()
    if not device:
        return Response({'error': 'No device assigned to this user'}, status=status.HTTP_404_NOT_FOUND)

    try:
        site = SolarSite.objects.get(device_id=device.id)
    except SolarSite.DoesNotExist:
        return Response({'error': 'No site found — use POST /users/{id}/site/ to create one'}, status=status.HTTP_404_NOT_FOUND)

    serializer = SolarSiteSerializer(site, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)


# ─── Device-centric Site endpoints ───────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsStaffUser])
def device_site(request: Any, device_id: int) -> Response:
    """
    GET  — return the solar site for a device, or 204 if none exists.
    POST — create a solar site linked directly to the device.
    """
    device = get_object_or_404(Device, pk=device_id)

    if request.method == 'GET':
        try:
            # Query only by device_id, avoiding the Device FK join
            site = SolarSite.objects.filter(device_id=device.id).first()
            if not site:
                return Response(status=status.HTTP_204_NO_CONTENT)
            
            # Manually serialize to avoid any FK issues
            data = {
                'id': site.id,
                'device_id': site.device_id,
                'site_id': site.site_id,
                'display_name': site.display_name,
                'latitude': site.latitude,
                'longitude': site.longitude,
                'capacity_kw': site.capacity_kw,
                'tilt_deg': site.tilt_deg,
                'azimuth_deg': site.azimuth_deg,
                'timezone': site.timezone,
                'is_active': site.is_active,
                'created_at': site.created_at.isoformat() if site.created_at else None,
                'updated_at': site.updated_at.isoformat() if site.updated_at else None,
            }
            return Response(data)
        except Exception as e:
            # Log error and return a proper error response
            import traceback
            error_details = traceback.format_exc()
            print(f"Error fetching site for device {device_id}: {str(e)}")
            print(error_details)
            return Response(
                {'error': 'Failed to retrieve site', 'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # POST — create
    if SolarSite.objects.filter(device_id=device.id).exists():
        return Response(
            {'error': 'Site already exists — use PUT to update'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    serializer = SolarSiteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    serializer.save(device=device)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['PUT'])
@permission_classes([IsStaffUser])
def device_site_update(request: Any, device_id: int) -> Response:
    """Update the solar site for a device."""
    device = get_object_or_404(Device, pk=device_id)
    try:
        site = SolarSite.objects.select_related('device').get(device_id=device.id)
    except SolarSite.DoesNotExist:
        return Response({'error': 'No site found — use POST to create one'}, status=status.HTTP_404_NOT_FOUND)

    serializer = SolarSiteSerializer(site, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)


# ─── DynamoDB Site Data endpoints ────────────────────────────────────────────
import boto3
from boto3.dynamodb.conditions import Key as DynamoKey
from decimal import Decimal


def _get_dynamo_table():
    """Build a boto3 DynamoDB Table resource from env config."""
    dynamodb = boto3.resource(
        'dynamodb',
        region_name=env_config('DYNAMODB_REGION', default='ap-south-1'),
        aws_access_key_id=env_config('AWS_ACCESS_KEY_ID', default=''),
        aws_secret_access_key=env_config('AWS_SECRET_ACCESS_KEY', default=''),
    )
    return dynamodb.Table(env_config('DYNAMODB_TABLE', default='meter_readings_actual'))


def _convert_decimals(obj):
    """Recursively convert boto3 Decimal values to float for JSON serialisation."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, list):
        return [_convert_decimals(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _convert_decimals(v) for k, v in obj.items()}
    return obj


def _check_site_auth(request, site_id: str) -> bool:
    """Return True if the requesting user is authorised to read this site."""
    if request.user.is_staff:
        return True
    return SolarSite.objects.filter(
        device__user=request.user, site_id=site_id, is_active=True
    ).exists()


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def site_telemetry(request: Any, site_id: str) -> Response:
    """
    Return TELEMETRY records for a site from DynamoDB.
    Query params:
      - start_date: ISO date string (default: 24h ago)
      - end_date: ISO date string (default: now)
      - days: number of days to look back (alternative to start_date)
    Staff sees any site; regular users only see their own.
    """
    if not _check_site_auth(request, site_id):
        return Response({'error': 'Not authorised to view this site'}, status=status.HTTP_403_FORBIDDEN)
    try:
        table = _get_dynamo_table()
        now_utc = datetime.now(dt_timezone.utc)
        
        # Parse date range from query params
        days = request.GET.get('days')
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            except:
                end_dt = now_utc
        else:
            end_dt = now_utc
            
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            except:
                start_dt = end_dt - timedelta(hours=24)
        elif days:
            try:
                start_dt = end_dt - timedelta(days=int(days))
            except:
                start_dt = end_dt - timedelta(hours=24)
        else:
            start_dt = end_dt - timedelta(hours=24)
        
        resp = table.query(
            KeyConditionExpression=DynamoKey('site_id').eq(site_id) & DynamoKey('timestamp').between(
                start_dt.strftime('%Y-%m-%dT%H:%M:%SZ'),
                end_dt.strftime('%Y-%m-%dT%H:%M:%SZ'),
            )
        )
        return Response(_convert_decimals(resp.get('Items', [])))
    except Exception as exc:
        logger.error('DynamoDB telemetry error site=%s: %s', site_id, exc)
        return Response([], status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def site_forecast(request: Any, site_id: str) -> Response:
    """
    Return FORECAST records (FORECAST#<date>…) for a site from DynamoDB.
    Query params:
      - date: ISO date string (default: today)
      - start_date: ISO date string for range query
      - end_date: ISO date string for range query
    """
    if not _check_site_auth(request, site_id):
        return Response({'error': 'Not authorised to view this site'}, status=status.HTTP_403_FORBIDDEN)
    try:
        table = _get_dynamo_table()
        
        # Parse date from query params
        date_param = request.GET.get('date')
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        
        if start_date and end_date:
            # Range query
            try:
                start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                start_str = f"FORECAST#{start_dt.strftime('%Y-%m-%d')}"
                end_str = f"FORECAST#{end_dt.strftime('%Y-%m-%d')}~"  # ~ is after all times
                resp = table.query(
                    KeyConditionExpression=DynamoKey('site_id').eq(site_id)
                        & DynamoKey('timestamp').between(start_str, end_str),
                    ScanIndexForward=True,
                )
            except:
                # Fallback to today
                today = datetime.utcnow().strftime('%Y-%m-%d')
                resp = table.query(
                    KeyConditionExpression=DynamoKey('site_id').eq(site_id)
                        & DynamoKey('timestamp').begins_with(f'FORECAST#{today}'),
                    ScanIndexForward=True,
                )
        else:
            # Single day query
            if date_param:
                try:
                    target_date = datetime.fromisoformat(date_param.replace('Z', '+00:00')).strftime('%Y-%m-%d')
                except:
                    target_date = datetime.utcnow().strftime('%Y-%m-%d')
            else:
                target_date = datetime.utcnow().strftime('%Y-%m-%d')
            
            query_prefix = f'FORECAST#{target_date}'
            logger.info('DynamoDB forecast query: site_id=%s, timestamp begins_with=%s', site_id, query_prefix)
                
            resp = table.query(
                KeyConditionExpression=DynamoKey('site_id').eq(site_id)
                    & DynamoKey('timestamp').begins_with(query_prefix),
                ScanIndexForward=True,
            )
            
            items = resp.get('Items', [])
            logger.info('DynamoDB forecast result: %d items found for site=%s', len(items), site_id)
            if items:
                logger.info('First item timestamp: %s', items[0].get('timestamp', 'N/A'))
        
        return Response(_convert_decimals(resp.get('Items', [])))
    except Exception as exc:
        logger.error('DynamoDB forecast error site=%s: %s', site_id, exc)
        return Response([], status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def site_weather(request: Any, site_id: str) -> Response:
    """
    Return weather data for a site from DynamoDB.

    Response shape:
      {
        "current":         { obs_timestamp, ghi_wm2, temperature_c, humidity_pct,
                             wind_speed_ms, cloud_cover_pct, fetched_at, source },
        "hourly_forecast": [ { forecast_for, ghi_wm2, temperature_c, humidity_pct,
                               wind_speed_ms, cloud_cover_pct, fetched_at }, ... ]
      }

    "current"  — latest WEATHER_OBS# record (what Open-Meteo currently reports).
    "hourly_forecast" — up to 24 WEATHER_FCST# records for the next 24 h,
      sorted chronologically, for rendering a weather outlook on the dashboard.
    Both are written by the forecast-scheduler every 15 minutes.
    """
    if not _check_site_auth(request, site_id):
        return Response({'error': 'Not authorised to view this site'}, status=status.HTTP_403_FORBIDDEN)
    try:
        table = _get_dynamo_table()

        # 1. Latest current observation
        obs_resp = table.query(
            KeyConditionExpression=DynamoKey('site_id').eq(site_id)
                & DynamoKey('timestamp').begins_with('WEATHER_OBS#'),
            ScanIndexForward=False,
            Limit=1,
        )
        obs_items = _convert_decimals(obs_resp.get('Items', []))
        current = None
        if obs_items:
            raw = obs_items[0]
            current = {
                'obs_timestamp':   raw.get('timestamp', '').replace('WEATHER_OBS#', ''),
                'fetched_at':      raw.get('fetched_at', ''),
                'ghi_wm2':         raw.get('ghi_wm2', 0),
                'temperature_c':   raw.get('temperature_c', 0),
                'humidity_pct':    raw.get('humidity_pct', 0),
                'wind_speed_ms':   raw.get('wind_speed_ms', 0),
                'cloud_cover_pct': raw.get('cloud_cover_pct', 0),
                'source':          raw.get('source', 'open-meteo'),
            }

        # 2. Hourly weather forecast for the next 24 h
        now_utc = datetime.now(dt_timezone.utc)
        end_utc = now_utc + timedelta(hours=24)
        fcst_resp = table.query(
            KeyConditionExpression=DynamoKey('site_id').eq(site_id)
                & DynamoKey('timestamp').between(
                    f"WEATHER_FCST#{now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}",
                    f"WEATHER_FCST#{end_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}",
                ),
            ScanIndexForward=True,
        )
        hourly_forecast = [
            {
                'forecast_for':    item.get('timestamp', '').replace('WEATHER_FCST#', ''),
                'fetched_at':      item.get('fetched_at', ''),
                'ghi_wm2':         item.get('ghi_wm2', 0),
                'temperature_c':   item.get('temperature_c', 0),
                'humidity_pct':    item.get('humidity_pct', 0),
                'wind_speed_ms':   item.get('wind_speed_ms', 0),
                'cloud_cover_pct': item.get('cloud_cover_pct', 0),
            }
            for item in _convert_decimals(fcst_resp.get('Items', []))
        ]

        if current is None and not hourly_forecast:
            return Response(None, status=status.HTTP_204_NO_CONTENT)

        return Response({'current': current, 'hourly_forecast': hourly_forecast})

    except Exception as exc:
        logger.error('DynamoDB weather error site=%s: %s', site_id, exc)
        return Response(None, status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def site_debug_data(request: Any, site_id: str) -> Response:
    """
    Debug endpoint to see what data types exist for a site in DynamoDB.
    Returns sample timestamps and counts for each data type.
    """
    if not request.user.is_staff:
        return Response({'error': 'Staff only'}, status=status.HTTP_403_FORBIDDEN)
    try:
        table = _get_dynamo_table()
        
        # Query all items for the site (limited)
        resp = table.query(
            KeyConditionExpression=DynamoKey('site_id').eq(site_id),
            Limit=100,
        )
        items = resp.get('Items', [])
        
        # Categorize by timestamp prefix
        categories = {}
        for item in items:
            ts = item.get('timestamp', '')
            if ts.startswith('FORECAST#'):
                prefix = 'FORECAST'
            elif ts.startswith('WEATHER_OBS#'):
                prefix = 'WEATHER_OBS'
            elif 'T' in ts:  # ISO timestamp for telemetry
                prefix = 'TELEMETRY'
            else:
                prefix = 'OTHER'
            
            if prefix not in categories:
                categories[prefix] = {'count': 0, 'samples': []}
            categories[prefix]['count'] += 1
            if len(categories[prefix]['samples']) < 3:
                categories[prefix]['samples'].append(ts)
        
        return Response({
            'site_id': site_id,
            'total_items_sampled': len(items),
            'categories': categories,
        })
    except Exception as exc:
        logger.error('DynamoDB debug error site=%s: %s', site_id, exc)
        return Response({'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def site_history_s3(request: Any, site_id: str) -> Response:
    """
    Return historical telemetry from S3 for a given date range.

    S3 path layout (written by telemetry_writer Lambda per hour):
        telemetry_csv/{site_id}/{YYYY}/{MM}/{DD}/{HH}/data.csv

    Each CSV file has a header row and one data row per telemetry payload
    received in that hour.  Multiple files are concatenated and returned
    as a sorted JSON array — same shape as site_telemetry (DynamoDB).

    Query params:
      - start_date: ISO date/datetime string (required)
      - end_date:   ISO date/datetime string (required)

    Auth: staff may query any site; regular users only their own.
    """
    import csv as csv_mod
    import io

    if not _check_site_auth(request, site_id):
        return Response({'error': 'Not authorised to view this site'}, status=status.HTTP_403_FORBIDDEN)

    start_date = request.GET.get('start_date')
    end_date   = request.GET.get('end_date')
    if not start_date or not end_date:
        return Response({'error': 'start_date and end_date are required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        end_dt   = datetime.fromisoformat(end_date.replace('Z',   '+00:00'))
    except (ValueError, TypeError):
        return Response({'error': 'Invalid date format'}, status=status.HTTP_400_BAD_REQUEST)

    # ISO strings for timestamp range filtering (lexicographic comparison works for ISO format)
    start_iso = start_dt.strftime('%Y-%m-%dT%H:%M:%S')
    end_iso   = end_dt.strftime('%Y-%m-%dT%H:%M:%S')

    s3 = boto3.client(
        's3',
        region_name=env_config('DYNAMODB_REGION', default='ap-south-1'),
        aws_access_key_id=env_config('AWS_ACCESS_KEY_ID', default=''),
        aws_secret_access_key=env_config('AWS_SECRET_ACCESS_KEY', default=''),
    )
    bucket = env_config('S3_BUCKET', default='360watts-datalake-pilot')

    _NUMERIC_FIELDS = {
        'run_state', 'pv1_power_w', 'pv2_power_w', 'pv1_voltage_v', 'pv1_current_a',
        'pv2_voltage_v', 'pv2_current_a', 'ac_output_power_w', 'grid_power_w',
        'grid_voltage_v', 'grid_frequency_hz', 'battery_voltage_v', 'battery_soc_percent',
        'battery_current_a', 'battery_power_w', 'battery_temp_c', 'load_power_w',
        'inverter_temp_c', 'pv_today_kwh', 'grid_buy_today_kwh', 'grid_sell_today_kwh',
        'batt_charge_today_kwh', 'batt_discharge_today_kwh', 'load_today_kwh',
    }

    all_records: list = []
    current = start_dt.date()
    end_date_obj = end_dt.date()

    while current <= end_date_obj:
        # List all hourly CSV files for this day
        day_prefix = f'telemetry_csv/{site_id}/{current.year}/{current.month:02d}/{current.day:02d}/'
        try:
            paginator = s3.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=bucket, Prefix=day_prefix):
                for obj in page.get('Contents', []):
                    key = obj['Key']
                    if not key.endswith('.csv'):
                        continue
                    try:
                        body = s3.get_object(Bucket=bucket, Key=key)['Body'].read().decode('utf-8')
                        reader = csv_mod.DictReader(io.StringIO(body))
                        for row in reader:
                            ts = row.get('timestamp', '')
                            # Lexicographic ISO comparison — filter to requested window
                            if ts < start_iso or ts > end_iso:
                                continue
                            record: dict = {}
                            for k, v in row.items():
                                if v == '' or v is None:
                                    record[k] = None
                                elif k in _NUMERIC_FIELDS:
                                    try:
                                        record[k] = float(v)
                                    except (ValueError, TypeError):
                                        record[k] = v
                                else:
                                    record[k] = v
                            all_records.append(record)
                    except Exception as exc:
                        logger.warning('S3 history: error reading key=%s: %s', key, exc)
        except Exception as exc:
            logger.warning('S3 history: error listing prefix=%s: %s', day_prefix, exc)

        current += timedelta(days=1)

    all_records.sort(key=lambda r: str(r.get('timestamp', '')))
    logger.info('S3 history: site=%s start=%s end=%s → %d records', site_id, start_iso, end_iso, len(all_records))
    return Response(all_records)
