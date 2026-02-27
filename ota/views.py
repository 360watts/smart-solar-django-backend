from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.http import FileResponse, HttpResponse, Http404
from django.utils import timezone
from django.conf import settings
from django.urls import reverse
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import models as db_models
from datetime import timedelta
import os
import hashlib
import logging
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from botocore.config import Config

from api.models import Device
from .models import FirmwareVersion, DeviceUpdateLog, OTAConfig, DeviceTargetedFirmware, TargetedUpdate
from .serializers import (
    OTACheckSerializer,
    OTAResponseSerializer,
    DeviceUpdateLogSerializer,
    FirmwareVersionSerializer,
    OTAConfigSerializer,
    TargetedUpdateSerializer,
    DeviceTargetedFirmwareSerializer,
)

logger = logging.getLogger(__name__)


def _auto_fail_stale_logs(campaign):
    """
    Mark CHECKING / AVAILABLE / DOWNLOADING logs that haven't been updated
    within OTA_UPDATE_TIMEOUT_MINUTES as FAILED and update campaign counters.
    Returns the number of logs that were auto-failed.
    """
    timeout_minutes = getattr(settings, 'OTA_UPDATE_TIMEOUT_MINUTES', 30)
    cutoff = timezone.now() - timedelta(minutes=timeout_minutes)

    stale_qs = DeviceUpdateLog.objects.filter(
        device__in=campaign.target_devices.all(),
        firmware_version=campaign.target_firmware,
        status__in=[
            DeviceUpdateLog.Status.CHECKING,
            DeviceUpdateLog.Status.AVAILABLE,
            DeviceUpdateLog.Status.DOWNLOADING,
        ],
        last_checked_at__lt=cutoff,
    )
    stale_count = stale_qs.count()
    if not stale_count:
        return 0

    now = timezone.now()
    # Capture device IDs BEFORE .update() — the queryset re-evaluates after
    # the status changes to FAILED and would return an empty list otherwise.
    stale_device_ids = list(
        stale_qs.values_list('device_id', flat=True)
    )
    stale_qs.update(
        status=DeviceUpdateLog.Status.FAILED,
        error_message=(
            f'Auto-failed: no activity for {timeout_minutes} minutes'
        ),
        completed_at=now,
    )

    # Also deactivate the device targets for stale devices so they stop
    # receiving the update command on heartbeat.
    DeviceTargetedFirmware.objects.filter(
        device_id__in=stale_device_ids,
        targeted_update=campaign,
        is_active=True,
    ).update(is_active=False)

    campaign.devices_failed = db_models.F('devices_failed') + stale_count
    campaign.save(update_fields=['devices_failed'])
    campaign.refresh_from_db(fields=['devices_failed', 'devices_updated', 'devices_total'])

    # Transition campaign to FAILED if all devices have now settled
    if (campaign.devices_updated + campaign.devices_failed) >= campaign.devices_total:
        if campaign.devices_updated < campaign.devices_total:
            campaign.status = TargetedUpdate.Status.FAILED
            campaign.completed_at = now
            campaign.save(update_fields=['status', 'completed_at'])

    logger.warning(
        'Auto-failed %d stale OTA log(s) for campaign %d (timeout=%dmin)',
        stale_count, campaign.id, timeout_minutes,
    )
    return stale_count


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
        
        # If the log was auto-failed, don't reopen it — tell the device no
        # update is available so it stops retrying against a dead campaign.
        if update_log and update_log.status == DeviceUpdateLog.Status.FAILED:
            logger.info(
                'OTA Check - Device %s log %s is FAILED, returning no-update',
                device_id, update_log.id,
            )
            return Response({
                'id': 'none',
                'version': current_firmware,
                'size': 0,
                'url': '',
                'status': 0,
            }, status=status.HTTP_200_OK)

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
        
        # Update is available — record when the device first learned about it
        update_log.firmware_version = latest_firmware
        update_log.status = DeviceUpdateLog.Status.AVAILABLE
        if not update_log.started_at:
            update_log.started_at = timezone.now()
        update_log.save()
        
        # Build download URL.
        # Priority: 1) CloudFront (short URL, modem-friendly)
        #           2) S3 presigned (if OTA_USE_PRESIGNED_URL=True)
        #           3) Django proxy fallback (default)
        download_url = None
        url_type = 'direct'
        url_ttl = None

        try:
            # --- 1. CloudFront ---
            cf_domain = getattr(settings, 'OTA_CLOUDFRONT_DOMAIN', '')
            if cf_domain:
                file_name = latest_firmware.file.name
                aws_location = getattr(settings, 'AWS_LOCATION', '')
                if aws_location and not file_name.startswith(aws_location + '/'):
                    cf_key = f"{aws_location}/{file_name}"
                else:
                    cf_key = file_name
                download_url = f"https://{cf_domain}/{cf_key}"
                url_type = 'cloudfront'
                logger.info(f"CloudFront URL for firmware {latest_firmware.version}: {download_url}")

            # --- 2. S3 presigned (fallback when CF not configured) ---
            if not download_url:
                try:
                    from storages.backends.s3boto3 import S3Boto3Storage
                    is_s3 = isinstance(latest_firmware.file.storage, S3Boto3Storage)
                except Exception:
                    is_s3 = False

                use_presigned = getattr(settings, 'OTA_USE_PRESIGNED_URL', False)
                if use_presigned and is_s3 and getattr(settings, 'AWS_STORAGE_BUCKET_NAME', None):
                    s3_config = Config(
                        signature_version='s3v4',
                        s3={'addressing_style': 'path'}
                    )
                    s3_client = boto3.client(
                        's3',
                        aws_access_key_id=getattr(settings, 'AWS_ACCESS_KEY_ID', None),
                        aws_secret_access_key=getattr(settings, 'AWS_SECRET_ACCESS_KEY', None),
                        region_name=getattr(settings, 'AWS_S3_REGION_NAME', None),
                        endpoint_url=getattr(settings, 'AWS_S3_ENDPOINT_URL', None) or None,
                        config=s3_config
                    )
                    file_name = latest_firmware.file.name
                    aws_location = getattr(settings, 'AWS_LOCATION', '')
                    key = f"{aws_location}/{file_name}" if aws_location and not file_name.startswith(aws_location + '/') else file_name

                    expires = getattr(settings, 'AWS_PRESIGNED_URL_EXPIRATION', 300)
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
            logger.debug(f"URL generation skipped or failed: {e}")

        # --- 3. Django proxy (always available as final fallback) ---
        if not download_url:
            download_url = request.build_absolute_uri(
                reverse('ota_download', kwargs={'firmware_id': latest_firmware.id})
            )

        # Always build the Django proxy URL so it can be sent as a fallback
        proxy_url = request.build_absolute_uri(
            reverse('ota_download', kwargs={'firmware_id': latest_firmware.id})
        )

        response_data = {
            'id': f'fw_{latest_firmware.id}',
            'version': latest_firmware.version,
            'size': latest_firmware.size,
            'url': download_url,
            'fallback_url': proxy_url,
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
        
        # Return file — with Range request support for chunked OTA downloads
        file_size = firmware.size
        range_header = request.META.get('HTTP_RANGE', '').strip()

        if range_header:
            try:
                range_spec = range_header.replace('bytes=', '')
                range_start_str, range_end_str = range_spec.split('-')
                range_start = int(range_start_str)
                range_end = int(range_end_str) if range_end_str else file_size - 1
                range_end = min(range_end, file_size - 1)
                chunk_size = range_end - range_start + 1

                # For S3-backed storage use boto3 GetObject with Range so only the
                # requested bytes are transferred from S3 (not the whole file).
                data = None
                try:
                    from storages.backends.s3boto3 import S3Boto3Storage
                    if isinstance(firmware.file.storage, S3Boto3Storage):
                        s3_client = boto3.client(
                            's3',
                            aws_access_key_id=getattr(settings, 'AWS_ACCESS_KEY_ID', None),
                            aws_secret_access_key=getattr(settings, 'AWS_SECRET_ACCESS_KEY', None),
                            region_name=getattr(settings, 'AWS_S3_REGION_NAME', 'us-east-1'),
                        )
                        file_name = firmware.file.name
                        aws_location = getattr(settings, 'AWS_LOCATION', '')
                        key = f"{aws_location}/{file_name}" if aws_location and not file_name.startswith(aws_location + '/') else file_name
                        s3_resp = s3_client.get_object(
                            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                            Key=key,
                            Range=f'bytes={range_start}-{range_end}',
                        )
                        data = s3_resp['Body'].read()
                        logger.info(f"OTA Range [S3] - Firmware: {firmware.version}, bytes={range_start}-{range_end}/{file_size}")
                except Exception as s3_err:
                    logger.warning(f"S3 range read failed ({s3_err}), falling back to local seek")

                if data is None:
                    # Fallback for local/non-S3 storage
                    f = firmware.file.open('rb')
                    f.seek(range_start)
                    data = f.read(chunk_size)
                    f.close()
                    logger.info(f"OTA Range [local] - Firmware: {firmware.version}, bytes={range_start}-{range_end}/{file_size}")

                response = HttpResponse(data, status=206, content_type='application/octet-stream')
                response['Content-Range'] = f'bytes {range_start}-{range_end}/{file_size}'
                response['Content-Length'] = chunk_size
                response['Content-Disposition'] = f'attachment; filename="{firmware.filename}"'
                response['Accept-Ranges'] = 'bytes'
            except Exception as e:
                logger.warning(f"OTA Range parse error ({range_header}): {e} — serving full file")
                response = FileResponse(firmware.file.open('rb'))
                response['Content-Type'] = 'application/octet-stream'
                response['Content-Disposition'] = f'attachment; filename="{firmware.filename}"'
                response['Content-Length'] = file_size
                response['Accept-Ranges'] = 'bytes'
        else:
            response = FileResponse(firmware.file.open('rb'))
            response['Content-Type'] = 'application/octet-stream'
            response['Content-Disposition'] = f'attachment; filename="{firmware.filename}"'
            response['Content-Length'] = file_size
            response['Accept-Ranges'] = 'bytes'

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
    """Get details of a targeted update campaign, with per-device log status."""
    try:
        update = TargetedUpdate.objects.get(id=update_id)

        # Auto-fail any stuck in-progress logs before returning status
        if update.status == TargetedUpdate.Status.IN_PROGRESS:
            _auto_fail_stale_logs(update)
            update.refresh_from_db()

        # TargetedUpdateSerializer already embeds enriched device_targets via
        # get_device_targets(), so a single serializer call is enough.
        data = TargetedUpdateSerializer(update).data
        return Response(data)
    except TargetedUpdate.DoesNotExist:
        return Response(
            {'error': 'Targeted update not found'},
            status=status.HTTP_404_NOT_FOUND,
        )


@api_view(['POST'])
@permission_classes([IsAdminUser])
def cancel_targeted_update(request, update_id):
    """Cancel a targeted update campaign"""
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


@api_view(['POST'])
@permission_classes([AllowAny])
def ota_status(request, device_id):
    """
    Device reports the result of an OTA update attempt.

    Called by the device after it has finished applying (or failing) the
    firmware update so the backend can immediately reflect the true state
    without waiting for the next ota_check.

    Request body:
    {
        "firmware_version": "0x00020000",   # version now running (success) or attempted (fail)
        "status": "completed" | "failed",
        "error": "optional human-readable error message"
    }
    """
    try:
        device = Device.objects.filter(device_serial=device_id).first()
        if not device:
            return Response({'error': 'Device not found'}, status=status.HTTP_404_NOT_FOUND)

        reported_version = request.data.get('firmware_version', '')
        reported_status = request.data.get('status', '').lower()
        error_msg = request.data.get('error', '')

        if reported_status not in ('completed', 'failed'):
            return Response(
                {'error': "status must be 'completed' or 'failed'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Find the most recent in-flight log for this device
        log = DeviceUpdateLog.objects.filter(
            device=device,
            status__in=[
                DeviceUpdateLog.Status.DOWNLOADING,
                DeviceUpdateLog.Status.AVAILABLE,
                DeviceUpdateLog.Status.CHECKING,
            ],
        ).order_by('-last_checked_at').first()

        if not log:
            return Response(
                {'message': 'No active update found for device', 'device_id': device_id},
                status=status.HTTP_200_OK,
            )

        now = timezone.now()
        log.last_checked_at = now
        log.completed_at = now

        # Resolve the active device target (if any) once, used in both branches
        device_target = DeviceTargetedFirmware.objects.filter(
            device=device, is_active=True
        ).select_related('targeted_update').first()

        if reported_status == 'completed':
            log.status = DeviceUpdateLog.Status.COMPLETED
            log.current_firmware = reported_version
            log.save(update_fields=['status', 'current_firmware', 'last_checked_at', 'completed_at'])
            logger.info('Device %s reported OTA success: %s', device_id, reported_version)

            if device_target:
                device_target.is_active = False
                device_target.save(update_fields=['is_active'])

                campaign = device_target.targeted_update
                if campaign:
                    campaign.devices_updated += 1
                    if campaign.devices_updated >= campaign.devices_total:
                        campaign.status = TargetedUpdate.Status.COMPLETED
                        campaign.completed_at = now
                    campaign.save(update_fields=['devices_updated', 'status', 'completed_at'])

        else:  # failed
            log.status = DeviceUpdateLog.Status.FAILED
            log.error_message = error_msg or 'Device reported update failure'
            log.save(update_fields=['status', 'error_message', 'last_checked_at', 'completed_at'])
            logger.warning('Device %s reported OTA failure: %s', device_id, error_msg)

            if device_target:
                device_target.is_active = False
                device_target.save(update_fields=['is_active'])

                campaign = device_target.targeted_update
                if campaign:
                    campaign.devices_failed += 1
                    settled = campaign.devices_updated + campaign.devices_failed
                    if settled >= campaign.devices_total:
                        if campaign.devices_updated < campaign.devices_total:
                            campaign.status = TargetedUpdate.Status.FAILED
                        else:
                            campaign.status = TargetedUpdate.Status.COMPLETED
                        campaign.completed_at = now
                    campaign.save(update_fields=['devices_failed', 'status', 'completed_at'])

        return Response({'message': f'OTA status {reported_status} recorded', 'device_id': device_id})

    except Exception as e:
        logger.error('OTA Status Error - Device: %s, Error: %s', device_id, str(e))
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
