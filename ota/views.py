from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.http import FileResponse
from django.utils import timezone
from django.conf import settings
from django.urls import reverse
import os
import logging

from api.models import Device
from .models import FirmwareVersion, DeviceUpdateLog, OTAConfig
from .serializers import (
    OTACheckSerializer,
    OTAResponseSerializer,
    DeviceUpdateLogSerializer,
    FirmwareVersionSerializer,
    OTAConfigSerializer,
)

logger = logging.getLogger(__name__)


@api_view(['POST', 'GET'])
@permission_classes([AllowAny])
def ota_check(request, device_id):
    """
    OTA Check Endpoint
    Device sends current firmware version, receives update info if available
    
    Request body: {
        "device_id": "stm32-device-001",
        "firmware_version": "0x00010000",
        "config_version": "0x00000001",  # optional
        "secret": "device-secret"  # optional for auth
    }
    
    Response: {
        "id": "ota_update_001",
        "version": "0x00020000",
        "size": 1048576,
        "url": "https://api.example.com/ota/firmware/ota_update_001/download",
        "checksum": "sha256_hash",
        "status": 1  # 1 = update available, 0 = no update
    }
    """
    try:
        # Get device
        device = get_object_or_404(Device, device_serial=device_id)
        
        # Parse request data
        if request.method == 'POST':
            data = request.data if hasattr(request, 'data') else request.POST.dict()
        else:
            data = request.GET.dict()
        
        current_firmware = data.get('firmware_version', '0x00010000')
        config_version = data.get('config_version', '')
        
        # Log the check request
        logger.info(f"OTA Check - Device: {device_id}, Current FW: {current_firmware}")
        
        # Get or create update log
        update_log, created = DeviceUpdateLog.objects.get_or_create(
            device=device,
            current_firmware=current_firmware,
            defaults={'status': DeviceUpdateLog.Status.CHECKING}
        )
        update_log.last_checked_at = timezone.now()
        update_log.attempt_count += 1
        
        # Find latest active firmware
        latest_firmware = FirmwareVersion.objects.filter(is_active=True).order_by('-created_at').first()
        
        if not latest_firmware:
            # No firmware available
            update_log.status = DeviceUpdateLog.Status.SKIPPED
            update_log.save()
            
            return Response({
                'id': 'none',
                'version': current_firmware,
                'size': 0,
                'url': '',
                'status': 0  # No update
            }, status=status.HTTP_200_OK)
        
        # Check if device needs update
        if current_firmware == latest_firmware.version:
            # Device is up to date
            update_log.status = DeviceUpdateLog.Status.COMPLETED
            update_log.save()
            
            return Response({
                'id': 'none',
                'version': latest_firmware.version,
                'size': latest_firmware.size,
                'url': '',
                'status': 0  # No update needed
            }, status=status.HTTP_200_OK)
        
        # Update is available
        update_log.firmware_version = latest_firmware
        update_log.status = DeviceUpdateLog.Status.AVAILABLE
        update_log.save()
        
        # Build download URL
        download_url = request.build_absolute_uri(
            reverse('ota_download', kwargs={'firmware_id': latest_firmware.id})
        )
        
        response_data = {
            'id': f'fw_{latest_firmware.id}',
            'version': latest_firmware.version,
            'size': latest_firmware.size,
            'url': download_url,
            'checksum': latest_firmware.checksum or '',
            'status': 1  # Update available
        }
        
        logger.info(f"OTA Update Available - Device: {device_id}, FW: {latest_firmware.version}, URL: {download_url}")
        
        return Response(response_data, status=status.HTTP_200_OK)
        
    except Device.DoesNotExist:
        logger.warning(f"OTA Check - Device not found: {device_id}")
        return Response({
            'error': 'Device not found',
            'device_id': device_id
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"OTA Check Error - Device: {device_id}, Error: {str(e)}")
        return Response({
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def ota_download(request, firmware_id):
    """
    Firmware Download Endpoint
    Stream firmware file to device
    """
    try:
        firmware = get_object_or_404(FirmwareVersion, id=firmware_id)
        
        if not firmware.file:
            return Response(
                {'error': 'Firmware file not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        logger.info(f"OTA Download - Firmware: {firmware.version}, File: {firmware.filename}")
        
        # Log download attempt
        device_serial = request.query_params.get('device', 'unknown')
        
        # Update log if device is known
        if device_serial != 'unknown':
            try:
                update_logs = DeviceUpdateLog.objects.filter(
                    firmware_version=firmware,
                    device__device_serial=device_serial
                )
                for log in update_logs:
                    log.status = DeviceUpdateLog.Status.DOWNLOADING
                    log.started_at = timezone.now()
                    log.save()
            except:
                pass
        
        # Return file
        response = FileResponse(firmware.file.open('rb'))
        response['Content-Type'] = 'application/octet-stream'
        response['Content-Disposition'] = f'attachment; filename="{firmware.filename}"'
        response['Content-Length'] = firmware.size
        
        return response
        
    except FirmwareVersion.DoesNotExist:
        return Response(
            {'error': 'Firmware not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"OTA Download Error - Firmware ID: {firmware_id}, Error: {str(e)}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def device_update_logs(request, device_id):
    """Get update history for a specific device"""
    try:
        device = get_object_or_404(Device, device_serial=device_id)
        logs = DeviceUpdateLog.objects.filter(device=device).order_by('-last_checked_at')
        serializer = DeviceUpdateLogSerializer(logs, many=True)
        return Response(serializer.data)
    except Device.DoesNotExist:
        return Response(
            {'error': 'Device not found'},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def firmware_versions_list(request):
    """List all available firmware versions"""
    active_only = request.query_params.get('active', 'true').lower() == 'true'
    
    if active_only:
        versions = FirmwareVersion.objects.filter(is_active=True).order_by('-created_at')
    else:
        versions = FirmwareVersion.objects.all().order_by('-created_at')
    
    serializer = FirmwareVersionSerializer(versions, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAdminUser])
def create_firmware_version(request):
    """Create a new firmware version (admin only)"""
    serializer = FirmwareVersionSerializer(data=request.data)
    if serializer.is_valid():
        firmware = serializer.save(created_by=request.user)
        logger.info(f"Firmware Created - Version: {firmware.version}, Created by: {request.user.username}")
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PATCH'])
@permission_classes([IsAdminUser])
def update_firmware_version(request, firmware_id):
    """Update firmware version status (admin only)"""
    try:
        firmware = get_object_or_404(FirmwareVersion, id=firmware_id)
        serializer = FirmwareVersionSerializer(firmware, data=request.data, partial=True)
        if serializer.is_valid():
            firmware = serializer.save(updated_by=request.user)
            logger.info(f"Firmware Updated - Version: {firmware.version}, Updated by: {request.user.username}")
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    except FirmwareVersion.DoesNotExist:
        return Response(
            {'error': 'Firmware not found'},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['GET'])
@permission_classes([IsAdminUser])
def get_ota_config(request):
    """Get OTA configuration (admin only)"""
    config, created = OTAConfig.objects.get_or_create(pk=1)
    serializer = OTAConfigSerializer(config)
    return Response(serializer.data)


@api_view(['PATCH'])
@permission_classes([IsAdminUser])
def update_ota_config(request):
    """Update OTA configuration (admin only)"""
    config, created = OTAConfig.objects.get_or_create(pk=1)
    serializer = OTAConfigSerializer(config, data=request.data, partial=True)
    if serializer.is_valid():
        config = serializer.save(updated_by=request.user)
        logger.info(f"OTA Config Updated by: {request.user.username}")
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([AllowAny])
def ota_health(request):
    """Health check endpoint for OTA service"""
    try:
        firmware_count = FirmwareVersion.objects.count()
        active_firmware = FirmwareVersion.objects.filter(is_active=True).count()
        return Response({
            'status': 'ok',
            'service': 'OTA',
            'firmware_versions': firmware_count,
            'active_firmware': active_firmware,
            'timestamp': timezone.now().isoformat()
        })
    except Exception as e:
        logger.error(f"OTA Health Check Error: {str(e)}")
        return Response({
            'status': 'error',
            'service': 'OTA',
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
