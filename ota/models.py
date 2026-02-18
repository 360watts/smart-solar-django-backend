from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.conf import settings
from django.utils.deconstruct import deconstructible
from api.models import Device


@deconstructible
class FirmwareStorage:
    """
    Lazy storage wrapper that ensures we use the correct storage backend.
    Django's default_storage is initialized at import time, which can happen
    before settings are fully configured, causing it to use FileSystemStorage
    even when S3 is configured in settings.
    
    Made deconstructible for Django migrations serialization.
    """
    _storage = None
    
    def __call__(self):
        if FirmwareStorage._storage is None:
            from django.utils.module_loading import import_string
            storage_path = getattr(settings, 'DEFAULT_FILE_STORAGE', 'django.core.files.storage.FileSystemStorage')
            storage_class = import_string(storage_path)
            FirmwareStorage._storage = storage_class()
        return FirmwareStorage._storage
    
    def __eq__(self, other):
        return isinstance(other, FirmwareStorage)


firmware_storage = FirmwareStorage()


class FirmwareVersion(models.Model):
    """Firmware versions available for OTA updates"""
    
    version = models.CharField(max_length=32, unique=True, help_text="e.g., 0x00020000")
    filename = models.CharField(max_length=255)
    file = models.FileField(upload_to='firmware/', storage=firmware_storage, help_text="Firmware binary file")
    size = models.PositiveIntegerField(help_text="File size in bytes")
    checksum = models.CharField(max_length=64, blank=True, null=True, help_text="SHA256 checksum")
    description = models.TextField(blank=True, null=True)
    release_notes = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=False, db_index=True, help_text="Only active versions are offered to devices")
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='firmware_created')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='firmware_updated')
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = "Firmware Versions"
        indexes = [
            models.Index(fields=['is_active', '-created_at']),
        ]
    
    def __str__(self):
        return f"Firmware {self.version} - {self.filename}"


class DeviceUpdateLog(models.Model):
    """Track firmware update attempts/downloads for each device"""
    
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        CHECKING = 'checking', 'Checking for Updates'
        AVAILABLE = 'available', 'Update Available'
        DOWNLOADING = 'downloading', 'Downloading'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        SKIPPED = 'skipped', 'Skipped'
    
    device = models.ForeignKey(Device, related_name="update_logs", on_delete=models.CASCADE)
    firmware_version = models.ForeignKey(FirmwareVersion, related_name="device_logs", on_delete=models.SET_NULL, null=True, blank=True)
    current_firmware = models.CharField(max_length=32, help_text="Firmware version reported by device")
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING)
    bytes_downloaded = models.PositiveIntegerField(default=0)
    attempt_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True, null=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['device', '-last_checked_at']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"{self.device.device_serial} - {self.firmware_version.version if self.firmware_version else 'N/A'} ({self.status})"


class OTAConfig(models.Model):
    """Global OTA configuration"""
    
    enable_auto_update = models.BooleanField(default=False, help_text="Automatically push updates to devices")
    update_strategy = models.CharField(
        max_length=32,
        choices=[
            ('immediate', 'Immediate - Push updates immediately'),
            ('scheduled', 'Scheduled - Push during maintenance window'),
            ('manual', 'Manual - Wait for device to request'),
        ],
        default='manual'
    )
    max_concurrent_updates = models.PositiveIntegerField(default=5, help_text="Max devices updating simultaneously")
    firmware_retention_days = models.PositiveIntegerField(default=30, help_text="Keep old firmware files for N days")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        verbose_name_plural = "OTA Configuration"
    
    def __str__(self):
        return "OTA Configuration"


class TargetedUpdate(models.Model):
    """
    Track targeted firmware updates for specific devices.
    Allows three update modes:
    - Single device: One device targeted
    - Multiple devices: Multiple devices targeted
    - Version-based: All devices with specific current firmware version
    """
    
    class UpdateType(models.TextChoices):
        SINGLE = 'single', 'Single Device'
        MULTIPLE = 'multiple', 'Multiple Devices'
        VERSION_BASED = 'version_based', 'Version Based'
    
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        IN_PROGRESS = 'in_progress', 'In Progress'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'
        FAILED = 'failed', 'Failed'
    
    update_type = models.CharField(max_length=20, choices=UpdateType.choices)
    target_firmware = models.ForeignKey(FirmwareVersion, on_delete=models.CASCADE, related_name='targeted_updates')
    
    # For single and multiple device updates
    target_devices = models.ManyToManyField(Device, related_name='targeted_updates', blank=True)
    
    # For version-based updates
    source_version = models.CharField(max_length=32, blank=True, null=True, 
        help_text="Current firmware version to target (for version-based updates)")
    
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    devices_total = models.PositiveIntegerField(default=0)
    devices_updated = models.PositiveIntegerField(default=0)
    devices_failed = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='targeted_updates_created')
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.get_update_type_display()} Update to {self.target_firmware.version} ({self.status})"


class DeviceTargetedFirmware(models.Model):
    """
    Individual device-level targeting for firmware updates.
    When a device checks for OTA, if it has an active target, 
    that specific firmware is offered instead of the global active firmware.
    """
    device = models.OneToOneField(Device, on_delete=models.CASCADE, related_name='targeted_firmware')
    target_firmware = models.ForeignKey(FirmwareVersion, on_delete=models.CASCADE)
    targeted_update = models.ForeignKey(TargetedUpdate, on_delete=models.CASCADE, null=True, blank=True, related_name='device_targets')
    is_active = models.BooleanField(default=True, db_index=True, help_text="Whether this target is still active")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Device Targeted Firmware"
        verbose_name_plural = "Device Targeted Firmwares"
        indexes = [
            models.Index(fields=['is_active']),
        ]
    
    def __str__(self):
        return f"{self.device.device_serial} -> {self.target_firmware.version}"
