from rest_framework import serializers
from .models import FirmwareVersion, DeviceUpdateLog, OTAConfig, TargetedUpdate, DeviceTargetedFirmware
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


class TargetedUpdateSerializer(serializers.ModelSerializer):
    target_firmware_version = serializers.CharField(source='target_firmware.version', read_only=True)
    target_firmware_id = serializers.PrimaryKeyRelatedField(
        source='target_firmware', queryset=FirmwareVersion.objects.all(), write_only=True
    )
    target_device_serials = serializers.ListField(
        child=serializers.CharField(), write_only=True, required=False
    )
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    
    # Include device targets for status tracking
    device_targets = serializers.SerializerMethodField()
    target_firmware = FirmwareVersionSerializer(read_only=True)
    
    def get_device_targets(self, obj):
        """Return list of device targets with their status"""
        from .models import DeviceTargetedFirmware
        targets = DeviceTargetedFirmware.objects.filter(
            targeted_update=obj
        ).select_related('device', 'target_firmware')
        
        return [{
            'id': t.id,
            'device': {
                'device_serial': t.device.device_serial,
                'id': t.device.id
            },
            'is_active': t.is_active,
            'created_at': t.created_at,
        } for t in targets]
    
    class Meta:
        model = TargetedUpdate
        fields = [
            'id',
            'update_type',
            'target_firmware_id',
            'target_firmware',
            'target_firmware_version',
            'source_version',
            'status',
            'devices_total',
            'devices_updated',
            'devices_failed',
            'created_at',
            'created_by_username',
            'completed_at',
            'notes',
            'target_device_serials',
            'device_targets',
        ]
        read_only_fields = ['id', 'status', 'devices_total', 'devices_updated', 'devices_failed', 
                           'created_at', 'completed_at', 'created_by_username', 'device_targets', 'target_firmware']


class DeviceTargetedFirmwareSerializer(serializers.ModelSerializer):
    device_serial = serializers.CharField(source='device.device_serial', read_only=True)
    target_firmware_version = serializers.CharField(source='target_firmware.version', read_only=True)
    
    class Meta:
        model = DeviceTargetedFirmware
        fields = [
            'id',
            'device_serial',
            'target_firmware_version',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields
