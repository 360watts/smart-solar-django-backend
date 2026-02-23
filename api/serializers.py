from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Device, GatewayConfig, SlaveDevice, RegisterMapping, TelemetryData, UserProfile, Alert, SolarSite


class AlertSerializer(serializers.ModelSerializer):
    device_serial = serializers.CharField(source='device.device_serial', read_only=True)
    acknowledged_by_username = serializers.CharField(source='acknowledged_by.username', read_only=True, allow_null=True)
    resolved_by_username = serializers.CharField(source='resolved_by.username', read_only=True, allow_null=True)
    created_by_username = serializers.SerializerMethodField()
    
    class Meta:
        model = Alert
        fields = [
            'id', 'device', 'device_serial', 'alert_type', 'severity', 'status',
            'title', 'message', 'triggered_at', 'created_by_username',
            'acknowledged_at', 'acknowledged_by', 'acknowledged_by_username', 
            'resolved_at', 'resolved_by', 'resolved_by_username', 'metadata'
        ]
        read_only_fields = ['id', 'triggered_at', 'created_by_username',
                           'acknowledged_at', 'acknowledged_by', 'resolved_at', 'resolved_by']
    
    def get_created_by_username(self, obj):
        """Safely get created_by username, handling pre-migration state"""
        try:
            return obj.created_by.username if hasattr(obj, 'created_by') and obj.created_by else None
        except AttributeError:
            return None


class DeviceSerializer(serializers.ModelSerializer):
    user = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    created_by_username = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    updated_by_username = serializers.SerializerMethodField()
    updated_at = serializers.SerializerMethodField()

    class Meta:
        model = Device
        fields = ['id', 'device_serial', 'hw_id', 'model', 'user', 'provisioned_at', 'config_version',
                  'created_by_username', 'created_at', 'updated_by_username', 'updated_at']
        read_only_fields = ['id', 'provisioned_at', 'hw_id', 'model']

    def get_created_by_username(self, obj):
        try:
            if hasattr(obj, 'created_by') and obj.created_by:
                return obj.created_by.username
        except AttributeError:
            pass
        return None

    def get_created_at(self, obj):
        try:
            if hasattr(obj, 'provisioned_at') and obj.provisioned_at:
                return obj.provisioned_at.isoformat()
        except AttributeError:
            pass
        return None

    def get_updated_by_username(self, obj):
        try:
            if hasattr(obj, 'updated_by') and obj.updated_by:
                return obj.updated_by.username
        except AttributeError:
            pass
        return None

    def get_updated_at(self, obj):
        try:
            if hasattr(obj, 'updated_at') and obj.updated_at:
                return obj.updated_at.isoformat()
        except AttributeError:
            pass
        return None

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret['user'] = instance.user.username if instance.user else None
        return ret

    def validate_user(self, value):
        if not value:
            return None
        try:
            return User.objects.get(username=value)
        except User.DoesNotExist:
            raise serializers.ValidationError(f"User '{value}' does not exist")

    def create(self, validated_data):
        user = validated_data.pop('user', None)
        instance = super().create(validated_data)
        if user:
            instance.user = user
            instance.save()
        return instance

    def update(self, instance, validated_data):
        user = validated_data.pop('user', None)
        instance = super().update(instance, validated_data)
        if 'user' in self.initial_data:
            instance.user = user
            instance.save()
        return instance


class RegisterMappingSerializer(serializers.ModelSerializer):
	# Renamed fields to match firmware expectation (camelCase)
	numRegisters = serializers.IntegerField(source="num_registers")
	functionCode = serializers.IntegerField(source="function_code")
	dataType = serializers.IntegerField(source="data_type")
	scaleFactor = serializers.FloatField(source="scale_factor")
	offset = serializers.FloatField()

	class Meta:
		model = RegisterMapping
		fields = [
			"label",
			"address",
			"numRegisters",
			"functionCode",
			"dataType",
			"scaleFactor",
			"offset",
			"enabled",
		]


class SlaveDeviceSerializer(serializers.ModelSerializer):
	registers = RegisterMappingSerializer(many=True)
	slaveId = serializers.IntegerField(source="slave_id")
	deviceName = serializers.CharField(source="device_name")
	pollingIntervalMs = serializers.IntegerField(source="polling_interval_ms")
	timeoutMs = serializers.IntegerField(source="timeout_ms")

	class Meta:
		model = SlaveDevice
		fields = [
			"slaveId",
			"deviceName",
			"pollingIntervalMs",
			"timeoutMs",
			"enabled",
			"registers",
		]


class GatewayConfigSerializer(serializers.ModelSerializer):
	uartConfig = serializers.SerializerMethodField()
	slaves = SlaveDeviceSerializer(many=True)

	class Meta:
		model = GatewayConfig
		fields = [
			"configId",
			"updatedAt",
			"configSchemaVer",
			"uartConfig",
			"slaves",
		]

	configId = serializers.CharField(source="config_id")
	updatedAt = serializers.DateTimeField(source="updated_at")
	configSchemaVer = serializers.IntegerField(source="config_schema_ver")

	def get_uartConfig(self, obj):
		return {
			"baudRate": obj.baud_rate,
			"dataBits": obj.data_bits,
			"stopBits": obj.stop_bits,
			"parity": obj.parity,
		}


class ProvisionSerializer(serializers.Serializer):
	hwId = serializers.CharField()
	model = serializers.CharField(required=False, allow_blank=True)
	claimNonce = serializers.CharField(required=False, allow_blank=True)


class TelemetryIngestSerializer(serializers.Serializer):
	deviceId = serializers.CharField()
	timestamp = serializers.DateTimeField()
	dataType = serializers.CharField()
	value = serializers.FloatField()
	unit = serializers.CharField(required=False, allow_blank=True)
	slaveId = serializers.IntegerField(required=False)
	registerLabel = serializers.CharField(required=False, allow_blank=True)
	quality = serializers.CharField(required=False, allow_blank=True)

	def create(self, validated_data):
		device, _ = Device.objects.get_or_create(device_serial=validated_data["deviceId"])
		# Use dataType as registerLabel if not provided
		register_label = validated_data.get("registerLabel") or validated_data["dataType"]
		return TelemetryData.objects.create(
			device=device,
			timestamp=validated_data["timestamp"],
			data_type=validated_data["dataType"],
			value=validated_data["value"],
			unit=validated_data.get("unit"),
			slave_id=validated_data.get("slaveId"),
			register_label=register_label,
			quality=validated_data.get("quality", "good"),
		)


class TelemetryDataSerializer(serializers.ModelSerializer):
	deviceId = serializers.CharField(source="device.device_serial")

	class Meta:
		model = TelemetryData
		fields = [
			"deviceId",
			"timestamp",
			"data_type",
			"value",
			"unit",
			"slave_id",
			"register_label",
			"quality",
		]


class SolarSiteSerializer(serializers.ModelSerializer):
    device_serial = serializers.SerializerMethodField(read_only=True)
    
    def get_device_serial(self, obj):
        """Safely get device serial, handling potential FK issues."""
        try:
            return obj.device.device_serial if obj.device else None
        except Exception:
            return None

    class Meta:
        model = SolarSite
        fields = [
            'id', 'device_id', 'device_serial', 'site_id', 'display_name',
            'latitude', 'longitude', 'capacity_kw',
            'tilt_deg', 'azimuth_deg', 'timezone', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'device_id', 'device_serial', 'created_at', 'updated_at']