from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Device, GatewayConfig, SlaveDevice, RegisterMapping, TelemetryData, UserProfile, Customer, Alert


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


class CustomerSerializer(serializers.ModelSerializer):
    device_count = serializers.SerializerMethodField()
    created_by_username = serializers.SerializerMethodField()
    updated_by_username = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    updated_at = serializers.SerializerMethodField()
    
    class Meta:
        model = Customer
        fields = ['id', 'customer_id', 'first_name', 'last_name', 'email', 
                  'mobile_number', 'address', 'created_at', 'created_by_username',
                  'updated_at', 'updated_by_username', 'is_active', 'notes', 'device_count']
        read_only_fields = ['id', 'created_at', 'created_by_username',
                           'updated_at', 'updated_by_username']
    
    def get_device_count(self, obj):
        return obj.devices.count()
    
    def get_created_by_username(self, obj):
        """Safely get created_by username, handling pre-migration state"""
        try:
            return obj.created_by.username if hasattr(obj, 'created_by') and obj.created_by else None
        except AttributeError:
            return None
    
    def get_updated_by_username(self, obj):
        """Safely get updated_by username, handling pre-migration state"""
        try:
            return obj.updated_by.username if hasattr(obj, 'updated_by') and obj.updated_by else None
        except AttributeError:
            return None
    
    def get_created_at(self, obj):
        """Safely get created_at, handling pre-migration state"""
        try:
            return obj.created_at if hasattr(obj, 'created_at') else None
        except AttributeError:
            return None
    
    def get_updated_at(self, obj):
        """Safely get updated_at, handling pre-migration state"""
        try:
            return obj.updated_at if hasattr(obj, 'updated_at') else None
        except AttributeError:
            return None


class DeviceSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    customer_id = serializers.CharField(source='customer.customer_id', read_only=True)
    # User field - writable for backwards compatibility with legacy frontend
    user = serializers.CharField(write_only=False, required=False, allow_blank=True)
    # Audit trail fields
    created_by_username = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    updated_by_username = serializers.SerializerMethodField()
    updated_at = serializers.SerializerMethodField()

    class Meta:
        model = Device
        fields = ['id', 'device_serial', 'customer_id', 'customer_name', 'user', 'provisioned_at', 'config_version',
                  'created_by_username', 'created_at', 'updated_by_username', 'updated_at']
        read_only_fields = ['id', 'provisioned_at', 'customer_id', 'customer_name']
    
    def get_customer_name(self, obj):
        return f"{obj.customer.first_name} {obj.customer.last_name}"
    
    def get_created_by_username(self, obj):
        try:
            if hasattr(obj, 'created_by') and obj.created_by:
                return obj.created_by.username
        except AttributeError:
            pass
        return None
    
    def get_created_at(self, obj):
        try:
            # Use provisioned_at as created_at since devices don't have a separate created_at field
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
        """
        Override representation to return username instead of customer_id for user field
        """
        ret = super().to_representation(instance)
        # Return username if user is assigned, otherwise return None
        ret['user'] = instance.user.username if instance.user else None
        return ret

    def validate_user(self, value):
        """
        Validate that the username exists and return the User object
        """
        if not value:
            # Allow empty/null user assignment
            return None
        
        try:
            user = User.objects.get(username=value)
            return user
        except User.DoesNotExist:
            raise serializers.ValidationError(f"User '{value}' does not exist")

    def create(self, validated_data):
        # Extract user if provided
        user = validated_data.pop('user', None)
        
        # Handle customer assignment if provided
        customer_id = self.context.get('customer_id')
        if customer_id:
            try:
                customer = Customer.objects.get(customer_id=customer_id)
                validated_data['customer'] = customer
            except Customer.DoesNotExist:
                raise serializers.ValidationError({'customer': 'Customer not found'})
        
        # If no customer assigned, use or create default customer
        if 'customer' not in validated_data:
            from .models import Customer
            default_customer, _ = Customer.objects.get_or_create(
                customer_id="DEFAULT",
                defaults={
                    "first_name": "Unassigned",
                    "last_name": "Devices",
                    "email": "default@example.com",
                    "notes": "Default customer for newly provisioned devices"
                }
            )
            validated_data['customer'] = default_customer
        
        instance = super().create(validated_data)
        
        # Assign user if provided
        if user:
            instance.user = user
            instance.save()
        
        return instance

    def update(self, instance, validated_data):
        """
        Update device, including user field
        """
        # Extract user if provided
        user = validated_data.pop('user', None)
        
        # Update other fields
        instance = super().update(instance, validated_data)
        
        # Update user if provided in request
        if 'user' in self.initial_data:
            if user:
                instance.user = user
            else:
                instance.user = None
            instance.save()
        
        return instance


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