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
from django.db import models as db_models
import os
import hashlib
import logging

from api.models import Device
from .models import FirmwareVersion, DeviceUpdateLog, OTAConfig, DeviceTargetedFirmware
from .serializers import (
    OTACheckSerializer,
    OTAResponseSerializer,
    DeviceUpdateLogSerializer,
    FirmwareVersionSerializer,
    OTAConfigSerializer,
)

logger = logging.getLogger(__name__)
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from botocore.config import Config


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
        
        # Check for device-specific firmware target first (targeted update)
        targeted_firmware = None
        device_target = None
        try:
            device_target = DeviceTargetedFirmware.objects.select_related('target_firmware').filter(
                device=device, is_active=True
            ).first()
            if device_target:
                targeted_firmware = device_target.target_firmware
                logger.info(f"OTA Check - Device {device_id} has targeted firmware: {targeted_firmware.version}")
        except Exception as e:
            logger.error(f"Error getting targeted firmware: {e}")
        
        # Get or create update log - use firmware_version to make it unique
        # If there's a targeted firmware, look for that specific log
        if targeted_firmware:
            update_log = DeviceUpdateLog.objects.filter(
                device=device,
                firmware_version=targeted_firmware
            ).order_by('-last_checked_at').first()
            
            if not update_log:
                # Create new log for this targeted update
                update_log = DeviceUpdateLog.objects.create(
                    device=device,
                    firmware_version=targeted_firmware,
                    current_firmware=current_firmware,
                    status=DeviceUpdateLog.Status.CHECKING
                )
        else:
            # No targeted firmware, get the most recent log for this device
            update_log = DeviceUpdateLog.objects.filter(
                device=device
            ).order_by('-last_checked_at').first()
            
            if not update_log:
                # Create new log
                update_log = DeviceUpdateLog.objects.create(
                    device=device,
                    current_firmware=current_firmware,
                    status=DeviceUpdateLog.Status.CHECKING
                )
        
        # Update the log
        update_log.last_checked_at = timezone.now()
        update_log.current_firmware = current_firmware
        update_log.attempt_count += 1
        update_log.save()
        
        # If device has a specific target, use that; otherwise use global active firmware
        if targeted_firmware:
            latest_firmware = targeted_firmware
        else:
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
            
            # If device target exists and device is now up to date, mark as complete
            if targeted_firmware and device_target:
                try:
                    device_target.is_active = False  # Mark target as fulfilled
                    device_target.save()
                    
                    # Update the targeted update campaign counts
                    if device_target.targeted_update:
                        campaign = device_target.targeted_update
                        campaign.devices_updated += 1
                        if campaign.devices_updated >= campaign.devices_total:
                            campaign.status = 'completed'
                            campaign.completed_at = timezone.now()
                        campaign.save()
                        logger.info(f"Device {device_id} completed targeted update to {latest_firmware.version}")
                except Exception as e:
                    logger.error(f"Error updating device target: {e}")
            
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
        
        # Build download URL. Prefer returning a presigned S3 URL when S3 is configured
        download_url = None
        url_type = 'direct'
        url_ttl = None

        try:
            # Detect django-storages S3 backend
            try:
                from storages.backends.s3boto3 import S3Boto3Storage
                is_s3 = isinstance(latest_firmware.file.storage, S3Boto3Storage)
            except Exception:
                is_s3 = False

            if is_s3 and getattr(settings, 'AWS_STORAGE_BUCKET_NAME', None):
                # Configure S3 client with explicit config for regional endpoints
                s3_config = Config(
                    signature_version='s3v4',
                    s3={'addressing_style': 'path'}  # Use path-style URLs: s3.region.amazonaws.com/bucket/key
                )
                
                s3_client = boto3.client(
                    's3',
                    aws_access_key_id=getattr(settings, 'AWS_ACCESS_KEY_ID', None),
                    aws_secret_access_key=getattr(settings, 'AWS_SECRET_ACCESS_KEY', None),
                    region_name=getattr(settings, 'AWS_S3_REGION_NAME', None),
                    endpoint_url=getattr(settings, 'AWS_S3_ENDPOINT_URL', None) or None,
                    config=s3_config
                )
                # Build full S3 key with AWS_LOCATION prefix if needed
                file_name = latest_firmware.file.name
                aws_location = getattr(settings, 'AWS_LOCATION', '')
                
                # If file_name doesn't already include the location prefix, add it
                if aws_location and not file_name.startswith(aws_location + '/'):
                    key = f"{aws_location}/{file_name}"
                else:
                    key = file_name
                
                expires = getattr(settings, 'AWS_PRESIGNED_URL_EXPIRATION', 300)
                logger.debug(f"Generating presigned URL - Bucket: {settings.AWS_STORAGE_BUCKET_NAME}, Key: {key}")
                try:
                    presigned = s3_client.generate_presigned_url(
                        'get_object',
                        Params={'Bucket': settings.AWS_STORAGE_BUCKET_NAME, 'Key': key},
                        ExpiresIn=int(expires),
                    )
                    download_url = presigned
                    url_type = 's3_presigned'
                    url_ttl = int(expires)
                    logger.info(f"Generated presigned URL for firmware {latest_firmware.version}: {presigned}")
                except (BotoCoreError, ClientError) as e:
                    logger.warning(f"Presigned URL generation failed, falling back to proxy download: {e}")

        except Exception as e:
            logger.debug(f"Presigned URL flow skipped or failed: {e}")

        if not download_url:
            download_url = request.build_absolute_uri(
                reverse('ota_download', kwargs={'firmware_id': latest_firmware.id})
            )

        response_data = {
            'id': f'fw_{latest_firmware.id}',
            'version': latest_firmware.version,
            'size': latest_firmware.size,
            'url': download_url,
            'url_type': url_type,
            'url_ttl': url_ttl,
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
        
        # Update log if device is known - using bulk_update for efficiency
        if device_serial != 'unknown':
            try:
                update_logs = list(DeviceUpdateLog.objects.filter(
                    firmware_version=firmware,
                    device__device_serial=device_serial
                ))
                if update_logs:
                    now = timezone.now()
                    for log in update_logs:
                        log.status = DeviceUpdateLog.Status.DOWNLOADING
                        log.started_at = now
                    DeviceUpdateLog.objects.bulk_update(update_logs, ['status', 'started_at'])
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


# ==================== TARGETED OTA UPDATE ENDPOINTS ====================

@api_view(['POST'])
@permission_classes([IsAdminUser])
def trigger_single_device_update(request):
    """
    Trigger OTA update for a single device
    
    Request body:
    {
        "device_serial": "STM32-001",
        "firmware_id": 5,
        "notes": "Optional notes"
    }
    """
    from .models import TargetedUpdate, DeviceTargetedFirmware
    from .serializers import TargetedUpdateSerializer
    
    try:
        device_serial = request.data.get('device_serial')
        firmware_id = request.data.get('firmware_id')
        notes = request.data.get('notes', '')
        
        if not device_serial or not firmware_id:
            return Response(
                {'error': 'device_serial and firmware_id are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate device exists
        try:
            device = Device.objects.get(device_serial=device_serial)
        except Device.DoesNotExist:
            return Response(
                {'error': f'Device {device_serial} not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Validate firmware exists and is active
        try:
            firmware = FirmwareVersion.objects.get(id=firmware_id)
        except FirmwareVersion.DoesNotExist:
            return Response(
                {'error': f'Firmware ID {firmware_id} not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Create targeted update record
        targeted_update = TargetedUpdate.objects.create(
            update_type=TargetedUpdate.UpdateType.SINGLE,
            target_firmware=firmware,
            status=TargetedUpdate.Status.PENDING,
            devices_total=1,
            created_by=request.user,
            notes=notes
        )
        targeted_update.target_devices.add(device)
        
        # Create or update device-level firmware target
        DeviceTargetedFirmware.objects.update_or_create(
            device=device,
            defaults={
                'target_firmware': firmware,
                'targeted_update': targeted_update,
                'is_active': True,
                'is_rollback': False  # Normal firmware update
            }
        )
        
        # Create initial update log for tracking
        # Try to get current firmware from existing logs, fallback to 'unknown'
        existing_log = DeviceUpdateLog.objects.filter(device=device).order_by('-last_checked_at').first()
        current_fw = existing_log.current_firmware if existing_log else 'unknown'
        
        # Delete any existing logs for this device+firmware to avoid duplicates
        DeviceUpdateLog.objects.filter(device=device, firmware_version=firmware).delete()
        
        # Create fresh log for this deployment
        DeviceUpdateLog.objects.create(
            device=device,
            firmware_version=firmware,
            current_firmware=current_fw,
            status=DeviceUpdateLog.Status.PENDING,
            attempt_count=0
        )
        
        targeted_update.status = TargetedUpdate.Status.IN_PROGRESS
        targeted_update.save()
        
        logger.info(
            f"Single Device Update Triggered - Device: {device_serial}, "
            f"Firmware: {firmware.version}, By: {request.user.username}"
        )
        
        serializer = TargetedUpdateSerializer(targeted_update)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        logger.error(f"Single Device Update Error: {str(e)}")
        return Response(
            {'error': f'Failed to trigger update: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAdminUser])
def trigger_rollback(request):
    """
    Trigger firmware rollback for a single device.
    The device must already have the previous firmware stored locally.
    This simply sends a rollback command (updateFirmware: 2) via heartbeat.
    
    Request body:
    {
        "device_serial": "STM32-001",
        "notes": "Optional notes"
    }
    """
    try:
        device_serial = request.data.get('device_serial')
        notes = request.data.get('notes', '')
        
        if not device_serial:
            return Response(
                {'error': 'device_serial is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate device exists
        try:
            device = Device.objects.get(device_serial=device_serial)
        except Device.DoesNotExist:
            return Response(
                {'error': f'Device {device_serial} not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Set the rollback flag - device will receive updateFirmware: 2 on next heartbeat
        device.pending_rollback = True
        device.save(update_fields=['pending_rollback'])
        
        logger.info(
            f"Rollback Command Triggered - Device: {device_serial}, "
            f"By: {request.user.username}, Notes: {notes}"
        )
        
        return Response({
            'message': f'Rollback command queued for device {device_serial}',
            'device_serial': device_serial,
            'notes': notes,
            'info': 'Device will receive updateFirmware: 2 flag on next heartbeat'
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Rollback Error: {str(e)}")
        return Response(
            {'error': f'Failed to trigger rollback: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAdminUser])
def trigger_multi_device_update(request):
    """
    Trigger OTA update for multiple devices
    
    Request body:
    {
        "device_serials": ["STM32-001", "STM32-002", "STM32-003"],
        "firmware_id": 5,
        "notes": "Optional notes"
    }
    """
    from .models import TargetedUpdate, DeviceTargetedFirmware
    from .serializers import TargetedUpdateSerializer
    
    try:
        device_serials = request.data.get('device_serials', [])
        firmware_id = request.data.get('firmware_id')
        notes = request.data.get('notes', '')
        
        if not device_serials or not firmware_id:
            return Response(
                {'error': 'device_serials (list) and firmware_id are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not isinstance(device_serials, list) or len(device_serials) == 0:
            return Response(
                {'error': 'device_serials must be a non-empty list'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate firmware exists
        try:
            firmware = FirmwareVersion.objects.get(id=firmware_id)
        except FirmwareVersion.DoesNotExist:
            return Response(
                {'error': f'Firmware ID {firmware_id} not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Find valid devices
        devices = Device.objects.filter(device_serial__in=device_serials)
        found_serials = set(devices.values_list('device_serial', flat=True))
        missing_serials = set(device_serials) - found_serials
        
        if not devices.exists():
            return Response(
                {'error': 'No valid devices found', 'missing_devices': list(missing_serials)},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Create targeted update record
        targeted_update = TargetedUpdate.objects.create(
            update_type=TargetedUpdate.UpdateType.MULTIPLE,
            target_firmware=firmware,
            status=TargetedUpdate.Status.PENDING,
            devices_total=devices.count(),
            created_by=request.user,
            notes=notes
        )
        targeted_update.target_devices.set(devices)
        
        # Create device-level firmware targets for each device
        for device in devices:
            DeviceTargetedFirmware.objects.update_or_create(
                device=device,
                defaults={
                    'target_firmware': firmware,
                    'targeted_update': targeted_update,
                    'is_active': True,
                    'is_rollback': False  # Normal firmware update
                }
            )
            
            # Create initial update log for tracking
            # Try to get current firmware from existing logs, fallback to 'unknown'
            existing_log = DeviceUpdateLog.objects.filter(device=device).order_by('-last_checked_at').first()
            current_fw = existing_log.current_firmware if existing_log else 'unknown'
            
            # Delete any existing logs for this device+firmware to avoid duplicates
            DeviceUpdateLog.objects.filter(device=device, firmware_version=firmware).delete()
            
            # Create fresh log for this deployment
            DeviceUpdateLog.objects.create(
                device=device,
                firmware_version=firmware,
                current_firmware=current_fw,
                status=DeviceUpdateLog.Status.PENDING,
                attempt_count=0
            )
        
        targeted_update.status = TargetedUpdate.Status.IN_PROGRESS
        targeted_update.save()
        
        logger.info(
            f"Multi-Device Update Triggered - Devices: {devices.count()}, "
            f"Firmware: {firmware.version}, By: {request.user.username}"
        )
        
        response_data = TargetedUpdateSerializer(targeted_update).data
        if missing_serials:
            response_data['warning'] = f'{len(missing_serials)} devices not found'
            response_data['missing_devices'] = list(missing_serials)
        
        return Response(response_data, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        logger.error(f"Multi-Device Update Error: {str(e)}")
        return Response(
            {'error': f'Failed to trigger update: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAdminUser])
def trigger_version_based_update(request):
    """
    Trigger OTA update for all devices on a specific firmware version
    
    Request body:
    {
        "source_version": "0x00010000",  # Current firmware version to target
        "firmware_id": 5,                 # Target firmware to update to
        "notes": "Optional notes"
    }
    """
    from .models import TargetedUpdate, DeviceTargetedFirmware
    from .serializers import TargetedUpdateSerializer
    
    try:
        source_version = request.data.get('source_version')
        firmware_id = request.data.get('firmware_id')
        notes = request.data.get('notes', '')
        
        if not source_version or not firmware_id:
            return Response(
                {'error': 'source_version and firmware_id are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate firmware exists
        try:
            firmware = FirmwareVersion.objects.get(id=firmware_id)
        except FirmwareVersion.DoesNotExist:
            return Response(
                {'error': f'Firmware ID {firmware_id} not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Find devices on the source version by checking their latest update log
        # or use DeviceUpdateLog to find devices that last reported this version
        devices_on_version = Device.objects.filter(
            update_logs__current_firmware=source_version
        ).distinct()
        
        if not devices_on_version.exists():
            return Response(
                {'error': f'No devices found with firmware version {source_version}',
                 'message': 'Devices must have checked for updates at least once to be tracked'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Create targeted update record
        targeted_update = TargetedUpdate.objects.create(
            update_type=TargetedUpdate.UpdateType.VERSION_BASED,
            target_firmware=firmware,
            source_version=source_version,
            status=TargetedUpdate.Status.PENDING,
            devices_total=devices_on_version.count(),
            created_by=request.user,
            notes=notes
        )
        targeted_update.target_devices.set(devices_on_version)
        
        # Create device-level firmware targets
        for device in devices_on_version:
            DeviceTargetedFirmware.objects.update_or_create(
                device=device,
                defaults={
                    'target_firmware': firmware,
                    'targeted_update': targeted_update,
                    'is_active': True,
                    'is_rollback': False  # Normal firmware update
                }
            )
            
            # Create initial update log for tracking
            # For version-based updates, we know the source version
            # Delete any existing logs for this device+firmware to avoid duplicates
            DeviceUpdateLog.objects.filter(device=device, firmware_version=firmware).delete()
            
            # Create fresh log for this deployment
            DeviceUpdateLog.objects.create(
                device=device,
                firmware_version=firmware,
                current_firmware=source_version,
                status=DeviceUpdateLog.Status.PENDING,
                attempt_count=0
            )
        
        targeted_update.status = TargetedUpdate.Status.IN_PROGRESS
        targeted_update.save()
        
        logger.info(
            f"Version-Based Update Triggered - Source: {source_version}, "
            f"Target: {firmware.version}, Devices: {devices_on_version.count()}, "
            f"By: {request.user.username}"
        )
        
        serializer = TargetedUpdateSerializer(targeted_update)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        logger.error(f"Version-Based Update Error: {str(e)}")
        return Response(
            {'error': f'Failed to trigger update: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_targeted_updates(request):
    """List all targeted update campaigns"""
    from .models import TargetedUpdate
    from .serializers import TargetedUpdateSerializer
    
    status_filter = request.query_params.get('status', None)
    update_type = request.query_params.get('type', None)
    
    updates = TargetedUpdate.objects.all()
    
    if status_filter:
        updates = updates.filter(status=status_filter)
    if update_type:
        updates = updates.filter(update_type=update_type)
    
    serializer = TargetedUpdateSerializer(updates, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_targeted_update(request, update_id):
    """Get details of a targeted update campaign"""
    from .models import TargetedUpdate
    from .serializers import TargetedUpdateSerializer, DeviceTargetedFirmwareSerializer
    
    try:
        update = TargetedUpdate.objects.get(id=update_id)
        data = TargetedUpdateSerializer(update).data
        
        # Include list of targeted devices
        data['target_devices'] = [
            {
                'device_serial': d.device_serial,
                'has_updated': DeviceUpdateLog.objects.filter(
                    device=d,
                    firmware_version=update.target_firmware,
                    status=DeviceUpdateLog.Status.COMPLETED
                ).exists()
            }
            for d in update.target_devices.all()
        ]
        
        return Response(data)
    except TargetedUpdate.DoesNotExist:
        return Response(
            {'error': 'Targeted update not found'},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['POST'])
@permission_classes([IsAdminUser])
def cancel_targeted_update(request, update_id):
    """Cancel a targeted update campaign"""
    from .models import TargetedUpdate, DeviceTargetedFirmware
    
    try:
        update = TargetedUpdate.objects.get(id=update_id)
        
        if update.status in [TargetedUpdate.Status.COMPLETED, TargetedUpdate.Status.CANCELLED]:
            return Response(
                {'error': f'Cannot cancel update with status: {update.status}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Remove device-level targets for this campaign
        DeviceTargetedFirmware.objects.filter(targeted_update=update).delete()
        
        update.status = TargetedUpdate.Status.CANCELLED
        update.save()
        
        logger.info(f"Targeted Update Cancelled - ID: {update_id}, By: {request.user.username}")
        
        return Response({'message': 'Update cancelled successfully', 'id': update_id})
    except TargetedUpdate.DoesNotExist:
        return Response(
            {'error': 'Targeted update not found'},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_device_firmware_versions(request):
    """
    Get list of unique firmware versions currently in use by devices
    Useful for version-based update selection
    """
    versions = DeviceUpdateLog.objects.values('current_firmware').annotate(
        device_count=db_models.Count('device', distinct=True)
    ).order_by('-device_count')
    
    return Response([
        {
            'version': v['current_firmware'],
            'device_count': v['device_count']
        }
        for v in versions
    ])
