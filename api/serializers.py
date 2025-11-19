from rest_framework import serializers
from .models import Device, GatewayConfig, SlaveDevice, RegisterMapping, TelemetryData


class RegisterMappingSerializer(serializers.ModelSerializer):
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

	# rename fields for response to match firmware expectation
	numRegisters = serializers.IntegerField(source="num_registers")
	functionCode = serializers.IntegerField(source="function_code")
	dataType = serializers.IntegerField(source="data_type")
	scaleFactor = serializers.FloatField(source="scale_factor")


class SlaveDeviceSerializer(serializers.ModelSerializer):
	registers = RegisterMappingSerializer(many=True)

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

	slaveId = serializers.IntegerField(source="slave_id")
	deviceName = serializers.CharField(source="device_name")
	pollingIntervalMs = serializers.IntegerField(source="polling_interval_ms")
	timeoutMs = serializers.IntegerField(source="timeout_ms")


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
		return TelemetryData.objects.create(
			device=device,
			timestamp=validated_data["timestamp"],
			data_type=validated_data["dataType"],
			value=validated_data["value"],
			unit=validated_data.get("unit"),
			slave_id=validated_data.get("slaveId"),
			register_label=validated_data.get("registerLabel"),
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