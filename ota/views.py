from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.http import FileResponse, Http404
from django.utils import timezone
from django.conf import settings
from django.urls import reverse
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
import os
import hashlib
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
        # Get device - using filter instead of get_object_or_404 for better error handling
        device = Device.objects.filter(device_serial=device_id).first()
        if not device:
            logger.warning(f"OTA Check - Device not found: {device_id}")
            return Response({
                'error': 'Device not found',
                'device_id': device_id
            }, status=status.HTTP_404_NOT_FOUND)
        
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
        firmware = FirmwareVersion.objects.filter(id=firmware_id).first()
        if not firmware:
            return Response(
                {'error': 'Firmware not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
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
        
    except Http404:
        return Response(
            {'error': 'Firmware not found'},
            status=status.HTTP_404_NOT_FOUND
        )
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
    """
    Create a new firmware version (admin only)
    Handles multipart/form-data file upload
    """
    try:
        # Get file from request
        firmware_file = request.FILES.get('file')
        if not firmware_file:
            return Response(
                {'error': 'No firmware file provided', 'field': 'file'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get metadata
        version = request.data.get('version')
        description = request.data.get('description', '')
        release_notes = request.data.get('release_notes', '')
        is_active = request.data.get('is_active', 'false').lower() == 'true'
        
        if not version:
            return Response(
                {'error': 'Version is required', 'field': 'version'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if version already exists
        if FirmwareVersion.objects.filter(version=version).exists():
            return Response(
                {'error': f'Firmware version {version} already exists', 'field': 'version'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Read file content once for both checksum and storage
        # This avoids issues with file pointer seeking on different storage backends
        file_content = firmware_file.read()
        file_size = len(file_content)
        original_filename = firmware_file.name
        
        # Calculate SHA256 checksum from content
        checksum = hashlib.sha256(file_content).hexdigest()
        
        # Create a new ContentFile with the content (works with S3 and local storage)
        content_file = ContentFile(file_content, name=original_filename)
        
        # === COMPREHENSIVE STORAGE DEBUGGING ===
        logger.info("=" * 80)
        logger.info("STORAGE DEBUGGING - BEFORE MODEL CREATION")
        logger.info("=" * 80)
        
        # Check settings
        logger.info(f"1. Settings Configuration:")
        logger.info(f"   DEFAULT_FILE_STORAGE: {settings.DEFAULT_FILE_STORAGE}")
        logger.info(f"   USE_S3: {getattr(settings, 'USE_S3', 'NOT SET')}")
        logger.info(f"   AWS_STORAGE_BUCKET_NAME: {getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'NOT SET')}")
        logger.info(f"   AWS_S3_REGION_NAME: {getattr(settings, 'AWS_S3_REGION_NAME', 'NOT SET')}")
        logger.info(f"   AWS_LOCATION: {getattr(settings, 'AWS_LOCATION', 'NOT SET')}")
        logger.info(f"   MEDIA_ROOT: {settings.MEDIA_ROOT}")
        logger.info(f"   MEDIA_URL: {settings.MEDIA_URL}")
        
        # Check default_storage
        logger.info(f"2. Default Storage Object:")
        logger.info(f"   default_storage class: {default_storage.__class__.__name__}")
        logger.info(f"   default_storage module: {default_storage.__class__.__module__}")
        logger.info(f"   default_storage full path: {default_storage.__class__.__module__}.{default_storage.__class__.__name__}")
        
        # Check model field storage
        logger.info(f"3. FirmwareVersion Model Field Storage:")
        file_field = FirmwareVersion._meta.get_field('file')
        logger.info(f"   Field type: {file_field.__class__.__name__}")
        logger.info(f"   Field storage class: {file_field.storage.__class__.__name__}")
        logger.info(f"   Field storage module: {file_field.storage.__class__.__module__}")
        logger.info(f"   Field storage is default_storage: {file_field.storage is default_storage}")
        logger.info(f"   Field storage == default_storage: {file_field.storage == default_storage}")
        
        # Check if S3 storage has credentials
        if hasattr(file_field.storage, 'bucket_name'):
            logger.info(f"4. S3 Storage Configuration:")
            logger.info(f"   S3 Bucket: {getattr(file_field.storage, 'bucket_name', 'N/A')}")
            logger.info(f"   S3 Region: {getattr(file_field.storage, 'region_name', 'N/A')}")
            logger.info(f"   S3 Access Key ID: {getattr(file_field.storage, 'access_key', 'N/A')[:10]}..." if hasattr(file_field.storage, 'access_key') else "   No access_key attribute")
        else:
            logger.info(f"4. Storage is NOT S3 (no bucket_name attribute)")
            logger.info(f"   Storage location: {getattr(file_field.storage, 'location', 'N/A')}")
            logger.info(f"   Storage base_url: {getattr(file_field.storage, 'base_url', 'N/A')}")
        
        logger.info("=" * 80)
        
        # Create firmware version with ContentFile
        firmware = FirmwareVersion.objects.create(
            version=version,
            filename=original_filename,
            file=content_file,
            size=file_size,
            checksum=checksum,
            description=description,
            release_notes=release_notes,
            is_active=is_active,
            created_by=request.user
        )
        
        logger.info(
            f"Firmware Created - Version: {firmware.version}, "
            f"Size: {firmware.size} bytes, Checksum: {checksum[:16]}..., "
            f"Storage: {settings.DEFAULT_FILE_STORAGE}, "
            f"Created by: {request.user.username}"
        )
        
        # === STORAGE DEBUGGING - AFTER MODEL CREATION ===
        logger.info("=" * 80)
        logger.info("STORAGE DEBUGGING - AFTER MODEL CREATION")
        logger.info("=" * 80)
        
        # Verify file was saved - detailed diagnostics
        if firmware.file:
            logger.info(f"✅ Firmware file field populated: {firmware.file.name}")
            logger.info(f"   File URL: {firmware.file.url}")
            logger.info(f"   File storage class: {firmware.file.storage.__class__.__name__}")
            logger.info(f"   File storage module: {firmware.file.storage.__class__.__module__}")
            
            # Check if storage changed after save
            file_field = FirmwareVersion._meta.get_field('file')
            logger.info(f"   Model field storage (after save): {file_field.storage.__class__.__name__}")
            logger.info(f"   Instance file.storage == field.storage: {firmware.file.storage is file_field.storage}")
            
            # Try to verify file exists
            try:
                file_exists = firmware.file.storage.exists(firmware.file.name)
                file_size_check = firmware.file.size
                logger.info(f"   Storage.exists({firmware.file.name}): {file_exists}")
                logger.info(f"   File.size: {file_size_check} bytes")
                
                # If it's FileSystemStorage, show where it saved the file
                if firmware.file.storage.__class__.__name__ == 'FileSystemStorage':
                    import os
                    full_path = firmware.file.storage.path(firmware.file.name)
                    logger.error(f"❌ WARNING: Using FileSystemStorage instead of S3!")
                    logger.error(f"   File saved to: {full_path}")
                    logger.error(f"   File exists on disk: {os.path.exists(full_path)}")
                    logger.error(f"   This file will be LOST when Vercel container restarts!")
                
                if not file_exists:
                    logger.error(f"❌ WARNING: File does not exist in storage after save!")
                    logger.error(f"   This suggests upload failed silently")
            except Exception as verify_error:
                logger.error(f"❌ Could not verify file existence: {verify_error}")
                import traceback
                logger.error(f"   Traceback: {traceback.format_exc()}")
        else:
            logger.error("❌ Firmware file field is empty!")
        
        logger.info("=" * 80)
        
        serializer = FirmwareVersionSerializer(firmware)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        logger.error(f"Firmware Upload Error: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return Response(
            {'error': f'Failed to upload firmware: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


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


@api_view(['DELETE'])
@permission_classes([IsAdminUser])
def delete_firmware_version(request, firmware_id):
    """Delete firmware version (admin only)"""
    try:
        firmware = get_object_or_404(FirmwareVersion, id=firmware_id)
        
        # Check if firmware is currently active
        if firmware.is_active:
            return Response(
                {'error': 'Cannot delete active firmware. Deactivate it first.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        version = firmware.version
        filename = firmware.filename
        
        # Delete the file from storage (S3 or local)
        if firmware.file:
            try:
                firmware.file.delete(save=False)
                logger.info(f"Deleted firmware file: {firmware.file.name}")
            except Exception as e:
                logger.warning(f"Failed to delete firmware file: {str(e)}")
        
        # Delete the database record
        firmware.delete()
        
        logger.info(
            f"Firmware Deleted - Version: {version}, File: {filename}, "
            f"Deleted by: {request.user.username}"
        )
        
        return Response(
            {'message': f'Firmware version {version} deleted successfully'},
            status=status.HTTP_200_OK
        )
        
    except FirmwareVersion.DoesNotExist:
        return Response(
            {'error': 'Firmware not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"Firmware Delete Error - ID: {firmware_id}, Error: {str(e)}")
        return Response(
            {'error': f'Failed to delete firmware: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
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
        
        # Include storage backend info
        from django.conf import settings
        storage_backend = settings.DEFAULT_FILE_STORAGE
        use_s3 = 'storages' in storage_backend or 's3' in storage_backend.lower()
        
        response_data = {
            'status': 'ok',
            'service': 'OTA',
            'firmware_versions': firmware_count,
            'active_firmware': active_firmware,
            'storage_backend': storage_backend,
            'using_s3': use_s3,
            'timestamp': timezone.now().isoformat()
        }
        
        # Add S3 config details if using S3
        if use_s3 and hasattr(settings, 'AWS_STORAGE_BUCKET_NAME'):
            response_data['s3_bucket'] = settings.AWS_STORAGE_BUCKET_NAME
            response_data['s3_region'] = getattr(settings, 'AWS_S3_REGION_NAME', 'unknown')
            response_data['s3_configured'] = bool(settings.AWS_STORAGE_BUCKET_NAME)
        
        return Response(response_data)
    except Exception as e:
        logger.error(f"OTA Health Check Error: {str(e)}")
        return Response({
            'status': 'error',
            'service': 'OTA',
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
