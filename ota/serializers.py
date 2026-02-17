from rest_framework import serializers
from .models import FirmwareVersion, DeviceUpdateLog, OTAConfig
from api.models import Device


class FirmwareVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = FirmwareVersion
        fields = [
            'id',
            'version',
            'filename',
            'size',
            'checksum',
            'description',
            'release_notes',
            'is_active',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class DeviceUpdateLogSerializer(serializers.ModelSerializer):
    firmware_version = FirmwareVersionSerializer(read_only=True)
    device_serial = serializers.CharField(source='device.device_serial', read_only=True)
    
    class Meta:
        model = DeviceUpdateLog
        fields = [
            'id',
            'device_serial',
            'firmware_version',
            'current_firmware',
            'status',
            'bytes_downloaded',
            'attempt_count',
            'error_message',
            'started_at',
            'completed_at',
            'last_checked_at',
        ]
        read_only_fields = fields


class OTACheckSerializer(serializers.Serializer):
    """Serializer for device OTA check requests and responses"""
    device_id = serializers.CharField(required=True)
    firmware_version = serializers.CharField(required=True, help_text="Current firmware version on device (e.g., 0x00010000)")
    config_version = serializers.CharField(required=False, allow_blank=True)
    secret = serializers.CharField(required=False, allow_blank=True)
    
    def to_representation(self, data):
        """Convert internal data to API response format"""
        return data


class OTAResponseSerializer(serializers.Serializer):
    """Serializer for OTA check response"""
    id = serializers.CharField()
    version = serializers.CharField()
    size = serializers.IntegerField()
    url = serializers.URLField()
    checksum = serializers.CharField(required=False)
    status = serializers.IntegerField()  # 1 = update available, 0 = no update


class OTAConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = OTAConfig
        fields = [
            'enable_auto_update',
            'update_strategy',
            'max_concurrent_updates',
            'firmware_retention_days',
            'updated_at',
        ]
