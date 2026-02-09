from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.db import models, connection
from django.db.models import Q
from django.conf import settings
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
from .models import Device, TelemetryData, GatewayConfig, UserProfile, SlaveDevice, RegisterMapping
import logging
import jwt
import secrets
from datetime import datetime, timedelta

# Get JWT secret from environment variable with secure fallback
DEVICE_JWT_SECRET = env_config('DEVICE_JWT_SECRET', default=settings.SECRET_KEY)

logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([AllowAny])
def provision(request: Any) -> Response:
    """
    Provision endpoint: /api/devices/provision
    ESP32 sends: {"hwId": "MAC", "model": "esp32 wroom", "claimNonce": "IM_YOUR_DEVICE"}
    ESP32 expects: {"status": "success", "deviceId": "...", "provisionedAt": "...", "credentials": {...}}
    """
    logger.info(f"Provision request: {request.data}")
    
    serializer = ProvisionSerializer(data=request.data)
    if not serializer.is_valid():
        logger.error(f"Validation errors: {serializer.errors}")
        return Response({"status": "error", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
    
    data = serializer.validated_data
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
    
    # Create or get device
    device, created = Device.objects.get_or_create(device_serial=device_id)
    if created:
        device.provisioned_at = timezone.now()
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
    """
    logger.info(f"Config request from {device_id}: {request.data}")
    
    # Verify device exists
    device, _ = Device.objects.get_or_create(device_serial=device_id)
    
    # Get latest config
    config = GatewayConfig.objects.order_by("-updated_at").first()
    if not config:
        logger.warning("No configuration available")
        return Response({"message": "No configuration available"}, status=status.HTTP_404_NOT_FOUND)
    
    # Update device's config version
    device.config_version = config.config_id
    device.save(update_fields=["config_version"])
    
    # Serialize and return
    data = GatewayConfigSerializer(config).data
    logger.info(f"Sending config {config.config_id} to device {device_id}")
    
    return Response(data, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([AllowAny])
def heartbeat(request: Any, device_id: str) -> Response:
    """
    Heartbeat endpoint: /api/devices/{device_id}/heartbeat
    ESP32 sends: {"deviceId": "...", "uptimeSeconds": ..., "firmwareVersion": "...", ...}
    ESP32 expects: {"status": 1, "commands": {"updateConfig": 0/1, "reboot": 0/1, ...}}
    """
    logger.info(f"Heartbeat from {device_id}: {request.data}")
    
    # Get device
    device, _ = Device.objects.get_or_create(device_serial=device_id)
    
    # Get device's current config from request
    current_config_id = request.data.get("configId", "")
    
    # Get latest config from database
    latest_config = GatewayConfig.objects.order_by("-updated_at").first()
    
    # Determine if config update is needed
    update_config_needed = 0
    if latest_config:
        if current_config_id != latest_config.config_id:
            update_config_needed = 1
            logger.info(f"Config update needed: current={current_config_id}, latest={latest_config.config_id}")
    
    # Build response with commands
    response_data = {
        "status": 1,  # ESP32 checks for status == 1
        "serverTime": timezone.now().isoformat(),
        "commands": {
            "updateConfig": update_config_needed,
            "reboot": 0,
            "updateFirmware": 0,
            "updateNetwork": 0,
            "sendLogs": 0,
            "clearLogs": 0,
        },
        "message": "OK"
    }
    
    return Response(response_data, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([AllowAny])
def logs(request: Any, device_id: str) -> Response:
    """
    Logs endpoint: /api/devices/{device_id}/logs
    ESP32 sends log data when requested
    """
    logger.info(f"Logs from {device_id}: {len(request.data)} items")
    # Store logs (implement as needed)
    return Response({"status": "stored"}, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([AllowAny])
def telemetry_ingest(request: Any) -> Response:
    serializer = TelemetryIngestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    telemetry = serializer.save()
    return Response({"status": "stored", "id": telemetry.id}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([AllowAny])
def telemetry_latest(request: Any, device_serial: str) -> Response:
    limit = int(request.GET.get("limit", 10))
    qs = TelemetryData.objects.filter(device__device_serial=device_serial).order_by("-timestamp")[:limit]
    return Response(TelemetryDataSerializer(qs, many=True).data)


@api_view(["GET"])
def devices_list(request: Any) -> Response:
    """
    List all devices for React frontend
    """
    devices = Device.objects.all().order_by("-provisioned_at")
    data = []
    for device in devices:
        data.append({
            "device_serial": device.device_serial,
            "provisioned_at": device.provisioned_at.isoformat(),
            "config_version": device.config_version,
        })
    return Response(data)


@api_view(["GET"])
def config_get(request: Any) -> Response:
    """
    Get gateway configuration for React frontend
    """
    config = GatewayConfig.objects.order_by("-updated_at").first()
    if not config:
        return Response({"error": "No configuration available"}, status=status.HTTP_404_NOT_FOUND)
    
    return Response(GatewayConfigSerializer(config).data)


@api_view(["GET"])
def telemetry_all(request: Any) -> Response:
    """
    Get all telemetry data for React frontend
    """
    limit = int(request.GET.get("limit", 100))
    telemetry = TelemetryData.objects.all().order_by("-timestamp")[:limit]
    return Response(TelemetryDataSerializer(telemetry, many=True).data)


@api_view(["GET"])
def alerts_list(request: Any) -> Response:
    """
    Get system alerts for React frontend
    """
    # For now, generate mock alerts based on telemetry data
    alerts = []
    recent_telemetry = TelemetryData.objects.filter(timestamp__gte=timezone.now() - timedelta(hours=1))
    
    # Check for offline devices
    devices = Device.objects.all()
    for device in devices:
        last_heartbeat = recent_telemetry.filter(device=device).order_by("-timestamp").first()
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
def system_health(request: Any) -> Response:
    """
    Get system health metrics for React frontend
    """
    # Calculate system health metrics
    total_devices = Device.objects.count()
    active_devices = 0
    total_telemetry_points = TelemetryData.objects.count()
    
    # Count active devices (devices with telemetry in last hour)
    one_hour_ago = timezone.now() - timedelta(hours=1)
    active_device_ids = TelemetryData.objects.filter(
        timestamp__gte=one_hour_ago
    ).values_list('device_id', flat=True).distinct()
    active_devices = len(set(active_device_ids))
    
    # Calculate uptime (simplified - based on when first telemetry was received)
    first_telemetry = TelemetryData.objects.order_by("timestamp").first()
    uptime_seconds = 0
    if first_telemetry:
        uptime_seconds = (timezone.now() - first_telemetry.timestamp).total_seconds()
    
    # Database connection status
    db_status = "healthy"
    
    # MQTT broker status (simplified - assume healthy if we have recent data)
    recent_data = TelemetryData.objects.filter(timestamp__gte=timezone.now() - timedelta(minutes=5)).exists()
    mqtt_status = "healthy" if recent_data else "warning"
    
    return Response({
        "total_devices": total_devices,
        "active_devices": active_devices,
        "total_telemetry_points": total_telemetry_points,
        "uptime_seconds": uptime_seconds,
        "database_status": db_status,
        "mqtt_status": mqtt_status,
        "overall_health": "healthy" if active_devices > 0 else "warning"
    })


@api_view(["GET"])
def kpis(request: Any) -> Response:
    """
    Get key performance indicators for React frontend
    """
    # Calculate KPIs from telemetry data
    recent_data = TelemetryData.objects.filter(timestamp__gte=timezone.now() - timedelta(hours=24))
    
    kpis = {
        "total_energy_generated": 0,
        "average_voltage": 0,
        "average_current": 0,
        "system_efficiency": 0,
        "data_points_last_24h": recent_data.count(),
        "active_devices_24h": len(set(recent_data.values_list('device_id', flat=True).distinct()))
    }
    
    # Calculate averages
    voltage_readings = recent_data.filter(data_type="voltage").values_list('value', flat=True)
    current_readings = recent_data.filter(data_type="current").values_list('value', flat=True)
    power_readings = recent_data.filter(data_type="power").values_list('value', flat=True)
    
    if voltage_readings:
        kpis["average_voltage"] = sum(voltage_readings) / len(voltage_readings)
    if current_readings:
        kpis["average_current"] = sum(current_readings) / len(current_readings)
    if power_readings:
        kpis["total_energy_generated"] = sum(power_readings) * 24 / 1000  # kWh approximation
    
    # Calculate efficiency (simplified)
    if kpis["average_voltage"] > 0 and kpis["average_current"] > 0:
        kpis["system_efficiency"] = min(100, (kpis["average_voltage"] * kpis["average_current"]) / 100)  # Simplified efficiency calc
    
    return Response(kpis)


@api_view(['POST'])
@permission_classes([AllowAny])
def register_user(request):
    """
    Register a new user
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
def login_user(request):
    """
    Login user and return JWT tokens
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
        'is_staff': user.is_staff,
        'date_joined': user.date_joined,
    })


@api_view(['GET'])
def users_list(request):
    """
    List all users with profiles, with optional search
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
            'is_staff': user.is_staff,
            'is_superuser': user.is_superuser,
            'date_joined': user.date_joined.isoformat(),
        })
    return Response(data)


@api_view(['POST'])
def create_user(request):
    """
    Create a new user (admin only)
    """
    username = request.data.get('username')
    email = request.data.get('email')
    password = request.data.get('password')
    first_name = request.data.get('first_name', '')
    last_name = request.data.get('last_name', '')
    mobile_number = request.data.get('mobile_number', '')
    address = request.data.get('address', '')
    is_staff = request.data.get('is_staff', False)  # Get is_staff from request, default to False

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
            address=address
        )

        return Response({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'mobile_number': mobile_number,
            'address': address,
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
def update_user(request, user_id):
    """
    Update user and profile
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
    profile.save()
    
    return Response({
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'mobile_number': profile.mobile_number,
        'address': profile.address,
        'date_joined': user.date_joined.isoformat(),
    })


@api_view(['DELETE'])
def delete_user(request, user_id):
    """
    Delete a user and their profile (employees only)
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
def get_user_devices(request, user_id):
    """
    Get all devices assigned to a specific user
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
            'serial_number': device.serial_number,
            'name': device.name if hasattr(device, 'name') else device.serial_number,
            'status': device.status if hasattr(device, 'status') else 'unknown',
            'last_heartbeat': device.last_heartbeat.isoformat() if hasattr(device, 'last_heartbeat') and device.last_heartbeat else None,
        })
    
    return Response(device_list)


# ========== PROFILE MANAGEMENT ENDPOINTS ==========

@api_view(['GET'])
def get_profile(request):
    """
    Get the current logged-in user's profile
    """
    user = request.user
    if not user.is_authenticated:
        return Response({'error': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)
    
    profile = getattr(user, 'userprofile', None)
    
    return Response({
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'mobile_number': profile.mobile_number if profile else None,
        'address': profile.address if profile else None,
        'is_staff': user.is_staff,
        'is_superuser': user.is_superuser,
        'date_joined': user.date_joined.isoformat(),
    })


@api_view(['PUT'])
def update_profile(request):
    """
    Update the current logged-in user's profile
    """
    user = request.user
    if not user.is_authenticated:
        return Response({'error': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)
    
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
        'is_staff': user.is_staff,
        'is_superuser': user.is_superuser,
        'date_joined': user.date_joined.isoformat(),
    })


@api_view(['POST'])
def change_password(request):
    """
    Change the current logged-in user's password
    """
    user = request.user
    if not user.is_authenticated:
        return Response({'error': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)
    
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


# ========== CUSTOMER MANAGEMENT ENDPOINTS ==========

@api_view(['GET'])
def customers_list(request):
    """
    List all customers with optional search
    """
    from .serializers import CustomerSerializer
    from .models import Customer
    from django.db.models import Q
    
    search = request.GET.get('search', '').strip()
    customers = Customer.objects.all()
    
    if search:
        customers = customers.filter(
            Q(customer_id__icontains=search) |
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(email__icontains=search) |
            Q(mobile_number__icontains=search)
        )
    
    serializer = CustomerSerializer(customers, many=True)
    return Response(serializer.data)


@api_view(['POST'])
def create_customer(request):
    """
    Create a new customer
    """
    from .serializers import CustomerSerializer
    from .models import Customer
    
    # Auto-generate customer_id if not provided
    if not request.data.get('customer_id'):
        import uuid
        request.data['customer_id'] = f"CUST{uuid.uuid4().hex[:8].upper()}"
    
    serializer = CustomerSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
def get_customer(request, customer_id):
    """
    Get a single customer by ID
    """
    from .serializers import CustomerSerializer
    from .models import Customer
    
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return Response({'error': 'Customer not found'}, status=status.HTTP_404_NOT_FOUND)
    
    serializer = CustomerSerializer(customer)
    return Response(serializer.data)


@api_view(['PUT'])
def update_customer(request, customer_id):
    """
    Update customer information
    """
    from .serializers import CustomerSerializer
    from .models import Customer
    
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return Response({'error': 'Customer not found'}, status=status.HTTP_404_NOT_FOUND)
    
    serializer = CustomerSerializer(customer, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['DELETE'])
def delete_customer(request, customer_id):
    """
    Delete a customer (admin only)
    """
    from .models import Customer
    
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return Response({'error': 'Customer not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Check if customer has devices
    if customer.devices.exists():
        return Response(
            {'error': f'Cannot delete customer with {customer.devices.count()} devices. Remove devices first.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    customer.delete()
    return Response({'message': 'Customer deleted successfully'})


@api_view(['GET'])
def presets_list(request):
    configs = GatewayConfig.objects.all().order_by('-updated_at')
    data = []
    for config in configs:
        slaves = SlaveDevice.objects.filter(gateway_config=config).count()

        # Format parity for display
        parity_display = {0: 'None', 1: 'Odd', 2: 'Even'}.get(config.parity, 'Unknown')

        data.append({
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
    return Response(data)


@api_view(['POST'])
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
def update_preset(request, preset_id):
    try:
        config = GatewayConfig.objects.get(id=preset_id)
    except GatewayConfig.DoesNotExist:
        return Response({'error': 'Preset not found'}, status=status.HTTP_404_NOT_FOUND)

    config.name = request.data.get('name', config.name)
    config.config_id = request.data.get('config_id', config.config_id)
    config.baud_rate = request.data.get('baud_rate', config.baud_rate)
    config.data_bits = request.data.get('data_bits', config.data_bits)
    config.stop_bits = request.data.get('stop_bits', config.stop_bits)
    config.parity = request.data.get('parity', config.parity)
    config.save()

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
def delete_preset(request, preset_id):
    try:
        config = GatewayConfig.objects.get(id=preset_id)
    except GatewayConfig.DoesNotExist:
        return Response({'error': 'Preset not found'}, status=status.HTTP_404_NOT_FOUND)

    config.delete()
    return Response({'message': 'Preset deleted'})


@api_view(['GET'])
def devices_list(request):
    search = request.GET.get('search', '')
    devices = Device.objects.all().order_by('-provisioned_at')

    if search:
        devices = devices.filter(
            Q(device_serial__icontains=search) |
            Q(user__username__icontains=search) |
            Q(config_version__icontains=search)
        )

    data = []
    for device in devices:
        data.append({
            'id': device.id,
            'device_serial': device.device_serial,
            'user': device.user.username if device.user else None,
            'provisioned_at': device.provisioned_at,
            'config_version': device.config_version,
        })
    return Response(data)


@api_view(['POST'])
def create_device(request):
    serializer = DeviceSerializer(data=request.data)
    if serializer.is_valid():
        device = serializer.save()
        return Response({
            'id': device.id,
            'device_serial': device.device_serial,
            'user': device.user.username if device.user else None,
            'provisioned_at': device.provisioned_at,
            'config_version': device.config_version,
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PUT'])
def update_device(request, device_id):
    try:
        device = Device.objects.get(id=device_id)
    except Device.DoesNotExist:
        return Response({'error': 'Device not found'}, status=status.HTTP_404_NOT_FOUND)

    serializer = DeviceSerializer(device, data=request.data, partial=True)
    if serializer.is_valid():
        device = serializer.save()
        return Response({
            'id': device.id,
            'device_serial': device.device_serial,
            'user': device.user.username if device.user else None,
            'provisioned_at': device.provisioned_at,
            'config_version': device.config_version,
        })
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['DELETE'])
def delete_device(request, device_id):
    print(f"Attempting to delete device with ID: {device_id}")
    print(f"Available devices: {list(Device.objects.values_list('id', 'device_serial'))}")
    try:
        device = Device.objects.get(id=device_id)
        print(f"Found device: {device.device_serial}")
    except Device.DoesNotExist:
        print(f"Device with ID {device_id} not found")
        return Response({'error': 'Device not found'}, status=status.HTTP_404_NOT_FOUND)

    device.delete()
    print(f"Device {device.device_serial} deleted successfully")
    return Response({'message': 'Device deleted'})


@api_view(['GET'])
def slaves_list(request, config_id):
    """
    Get all slaves for a gateway configuration
    """
    try:
        config = GatewayConfig.objects.get(config_id=config_id)
    except GatewayConfig.DoesNotExist:
        return Response({'error': 'Configuration not found'}, status=status.HTTP_404_NOT_FOUND)

    slaves = SlaveDevice.objects.filter(gateway_config=config).prefetch_related('registers')
    data = []
    for slave in slaves:
        registers = RegisterMapping.objects.filter(slave=slave)
        data.append({
            'id': slave.id,
            'slave_id': slave.slave_id,
            'device_name': slave.device_name,
            'polling_interval_ms': slave.polling_interval_ms,
            'timeout_ms': slave.timeout_ms,
            'enabled': slave.enabled,
            'registers': [{
                'id': reg.id,
                'label': reg.label,
                'address': reg.address,
                'num_registers': reg.num_registers,
                'function_code': reg.function_code,
                'data_type': reg.data_type,
                'scale_factor': reg.scale_factor,
                'offset': reg.offset,
                'enabled': reg.enabled,
            } for reg in registers]
        })
    return Response(data)


@api_view(['POST'])
def create_slave(request, config_id):
    """
    Create a new slave device for a gateway configuration
    """
    try:
        config = GatewayConfig.objects.get(config_id=config_id)
    except GatewayConfig.DoesNotExist:
        return Response({'error': 'Configuration not found'}, status=status.HTTP_404_NOT_FOUND)

    slave_id = request.data.get('slave_id')
    device_name = request.data.get('device_name')
    polling_interval_ms = request.data.get('polling_interval_ms', 5000)
    timeout_ms = request.data.get('timeout_ms', 1000)
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
                data_type=reg_data.get('data_type', 0),
                scale_factor=reg_data.get('scale_factor', 1.0),
                offset=reg_data.get('offset', 0.0),
                enabled=reg_data.get('enabled', True)
            )
            registers.append({
                'id': register.id,
                'label': register.label,
                'address': register.address,
                'num_registers': register.num_registers,
                'function_code': register.function_code,
                'data_type': register.data_type,
                'scale_factor': register.scale_factor,
                'offset': register.offset,
                'enabled': register.enabled,
            })

        return Response({
            'id': slave.id,
            'slave_id': slave.slave_id,
            'device_name': slave.device_name,
            'polling_interval_ms': slave.polling_interval_ms,
            'timeout_ms': slave.timeout_ms,
            'enabled': slave.enabled,
            'registers': registers
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PUT'])
def update_slave(request, config_id, slave_id):
    """
    Update a slave device
    """
    try:
        config = GatewayConfig.objects.get(config_id=config_id)
        slave = SlaveDevice.objects.get(gateway_config=config, slave_id=slave_id)
    except GatewayConfig.DoesNotExist:
        return Response({'error': 'Configuration not found'}, status=status.HTTP_404_NOT_FOUND)
    except SlaveDevice.DoesNotExist:
        return Response({'error': 'Slave not found'}, status=status.HTTP_404_NOT_FOUND)

    device_name = request.data.get('device_name', slave.device_name)
    polling_interval_ms = request.data.get('polling_interval_ms', slave.polling_interval_ms)
    timeout_ms = request.data.get('timeout_ms', slave.timeout_ms)
    enabled = request.data.get('enabled', slave.enabled)
    registers_data = request.data.get('registers', [])

    slave.device_name = device_name
    slave.polling_interval_ms = polling_interval_ms
    slave.timeout_ms = timeout_ms
    slave.enabled = enabled
    slave.save()

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
            data_type=reg_data.get('data_type', 0),
            scale_factor=reg_data.get('scale_factor', 1.0),
            offset=reg_data.get('offset', 0.0),
            enabled=reg_data.get('enabled', True)
        )
        registers.append({
            'id': register.id,
            'label': register.label,
            'address': register.address,
            'num_registers': register.num_registers,
            'function_code': register.function_code,
            'data_type': register.data_type,
            'scale_factor': register.scale_factor,
            'offset': register.offset,
            'enabled': register.enabled,
        })

    return Response({
        'id': slave.id,
        'slave_id': slave.slave_id,
        'device_name': slave.device_name,
        'polling_interval_ms': slave.polling_interval_ms,
        'timeout_ms': slave.timeout_ms,
        'enabled': slave.enabled,
        'registers': registers
    })


@api_view(['DELETE'])
def delete_slave(request, config_id, slave_id):
    """
    Delete a slave device
    """
    try:
        config = GatewayConfig.objects.get(config_id=config_id)
        slave = SlaveDevice.objects.get(gateway_config=config, slave_id=slave_id)
    except GatewayConfig.DoesNotExist:
        return Response({'error': 'Configuration not found'}, status=status.HTTP_404_NOT_FOUND)
    except SlaveDevice.DoesNotExist:
        return Response({'error': 'Slave not found'}, status=status.HTTP_404_NOT_FOUND)

    slave.delete()
    return Response({'message': 'Slave deleted successfully'})


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
def alerts_crud(request: Any) -> Response:
    """
    GET: List all alerts with optional filtering
    POST: Create a new alert
    """
    if request.method == 'GET':
        # Filter parameters
        device_serial = request.GET.get('device')
        severity = request.GET.get('severity')
        alert_status = request.GET.get('status')
        limit = int(request.GET.get('limit', 100))
        
        queryset = Alert.objects.all()
        
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
def alert_detail(request: Any, alert_id: int) -> Response:
    """
    GET: Retrieve a single alert
    PUT: Update an alert
    DELETE: Delete an alert
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
def alert_acknowledge(request: Any, alert_id: int) -> Response:
    """
    Acknowledge an alert
    """
    try:
        alert = Alert.objects.get(id=alert_id)
    except Alert.DoesNotExist:
        return Response({'error': 'Alert not found'}, status=status.HTTP_404_NOT_FOUND)
    
    alert.acknowledge(request.user)
    serializer = AlertSerializer(alert)
    return Response(serializer.data)


@api_view(['POST'])
def alert_resolve(request: Any, alert_id: int) -> Response:
    """
    Resolve an alert
    """
    try:
        alert = Alert.objects.get(id=alert_id)
    except Alert.DoesNotExist:
        return Response({'error': 'Alert not found'}, status=status.HTTP_404_NOT_FOUND)
    
    alert.resolve(request.user)
    serializer = AlertSerializer(alert)
    return Response(serializer.data)
