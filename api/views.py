from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from typing import Any
from django.utils import timezone
from .models import Device, GatewayConfig, TelemetryData
from .serializers import (
    ProvisionSerializer,
    GatewayConfigSerializer,
    TelemetryIngestSerializer,
    TelemetryDataSerializer,
)
import logging

logger = logging.getLogger(__name__)


@api_view(["POST"])
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
    hw_id = data["hwId"]
    
    # Create or get device using hwId as device_serial
    device, created = Device.objects.get_or_create(device_serial=hw_id)
    
    logger.info(f"Device {'created' if created else 'found'}: {hw_id}")
    
    # Return response matching ESP32 expectation
    return Response(
        {
            "status": "success",
            "deviceId": device.device_serial,
            "provisionedAt": device.provisioned_at.isoformat(),
            "credentials": {
                "type": "api-key",
                "secret": f"secret-{device.device_serial}"
            }
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
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
def logs(request: Any, device_id: str) -> Response:
    """
    Logs endpoint: /api/devices/{device_id}/logs
    ESP32 sends log data when requested
    """
    logger.info(f"Logs from {device_id}: {len(request.data)} items")
    # Store logs (implement as needed)
    return Response({"status": "stored"}, status=status.HTTP_200_OK)


@api_view(["POST"])
def telemetry_ingest(request: Any) -> Response:
    serializer = TelemetryIngestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    telemetry = serializer.save()
    return Response({"status": "stored", "id": telemetry.id}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def telemetry_latest(request: Any, device_serial: str) -> Response:
    limit = int(request.GET.get("limit", 10))
    qs = TelemetryData.objects.filter(device__device_serial=device_serial).order_by("-timestamp")[:limit]
    return Response(TelemetryDataSerializer(qs, many=True).data)
