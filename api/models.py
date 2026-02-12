from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError


class UserProfile(models.Model):
    """Profile for employees (staff users)"""
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    mobile_number = models.CharField(max_length=15, blank=True, null=True)
    address = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.user.username}'s profile"


class Customer(models.Model):
    """Solar system customers/device owners (separate from staff)"""
    customer_id = models.CharField(max_length=64, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    mobile_number = models.CharField(max_length=15, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='customers_created')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='customers_updated')
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.customer_id})"

    class Meta:
        ordering = ['-created_at']


class Device(models.Model):
	device_serial = models.CharField(max_length=64, unique=True)
	customer = models.ForeignKey(Customer, related_name="devices", on_delete=models.CASCADE)
	# Legacy field - will be removed after migration
	user = models.ForeignKey(User, related_name="legacy_devices", on_delete=models.SET_NULL, null=True, blank=True)
	public_key_algorithm = models.CharField(max_length=32, blank=True, null=True)
	csr_pem = models.TextField(blank=True, null=True)
	provisioned_at = models.DateTimeField(default=timezone.now)
	config_version = models.CharField(max_length=32, blank=True, null=True)
	created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='devices_created')
	updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='devices_updated')
	updated_at = models.DateTimeField(auto_now=True)

	def __str__(self):
		return self.device_serial


class GatewayConfig(models.Model):
	# Protocol Types
	class ProtocolType(models.TextChoices):
		RTU = 'RTU', 'Modbus RTU'
		ASCII = 'ASCII', 'Modbus ASCII'
		TCP = 'TCP', 'Modbus TCP'
	
	# Parity Options
	class ParityType(models.TextChoices):
		NONE = 'N', 'None'
		EVEN = 'E', 'Even'
		ODD = 'O', 'Odd'
	
	# Physical Interface Types
	class InterfaceType(models.TextChoices):
		RS485 = 'RS485', 'RS-485'
		RS232 = 'RS232', 'RS-232' 
		ETHERNET = 'ETH', 'Ethernet'
	
	config_id = models.CharField(max_length=64, unique=True)
	name = models.CharField(max_length=100, blank=True, default='')
	created_at = models.DateTimeField(default=timezone.now)
	created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='gateway_configs_created')
	updated_at = models.DateTimeField(auto_now=True)
	updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='gateway_configs_updated')
	config_schema_ver = models.PositiveIntegerField(default=1)
	
	# Communication Layer
	protocol_type = models.CharField(max_length=10, choices=ProtocolType.choices, default=ProtocolType.RTU)
	baud_rate = models.PositiveIntegerField(default=9600)
	parity = models.CharField(max_length=1, choices=ParityType.choices, default=ParityType.NONE)
	data_bits = models.PositiveSmallIntegerField(default=8, choices=[(7, '7 bits'), (8, '8 bits')])
	stop_bits = models.PositiveSmallIntegerField(default=1, choices=[(1, '1 bit'), (2, '2 bits')])
	interface_type = models.CharField(max_length=10, choices=InterfaceType.choices, default=InterfaceType.RS485)
	
	# Timing Configuration
	global_response_timeout_ms = models.PositiveIntegerField(default=1000, help_text='Default response timeout in ms')
	inter_frame_delay_ms = models.PositiveIntegerField(default=50, help_text='Gap between frames in ms')
	global_retry_count = models.PositiveSmallIntegerField(default=3, help_text='Default retry attempts')
	global_retry_delay_ms = models.PositiveIntegerField(default=100, help_text='Wait between retries in ms')
	global_poll_interval_ms = models.PositiveIntegerField(default=5000, help_text='Default polling interval in ms')

	def __str__(self):
		return self.name or self.config_id


class SlaveDevice(models.Model):
	# Priority Levels
	class PriorityLevel(models.TextChoices):
		HIGH = 'HIGH', 'High Priority'
		NORMAL = 'NORMAL', 'Normal Priority'
		LOW = 'LOW', 'Low Priority'
	
	gateway_config = models.ForeignKey(GatewayConfig, related_name="slaves", on_delete=models.CASCADE)
	slave_id = models.PositiveSmallIntegerField(validators=[models.validators.MinValueValidator(1), models.validators.MaxValueValidator(247)])
	device_name = models.CharField(max_length=64)
	device_type = models.CharField(max_length=64, blank=True, help_text='Device model for preset mappings')
	enabled = models.BooleanField(default=True)
	
	# Timing Configuration
	polling_interval_ms = models.PositiveIntegerField(default=5000)
	response_timeout_ms = models.PositiveIntegerField(default=1000)
	retry_count = models.PositiveSmallIntegerField(default=3)
	retry_delay_ms = models.PositiveIntegerField(default=100)
	priority = models.CharField(max_length=10, choices=PriorityLevel.choices, default=PriorityLevel.NORMAL)
	
	# Additional metadata
	description = models.TextField(blank=True, help_text='Device description or notes')
	preset = models.ForeignKey('DevicePreset', on_delete=models.SET_NULL, null=True, blank=True, help_text='Device preset template')

	class Meta:
		unique_together = ("gateway_config", "slave_id")
		ordering = ["slave_id"]

	def __str__(self):
		return f"{self.gateway_config.config_id}:slave:{self.slave_id}"


class RegisterMapping(models.Model):
	# Register Types
	class RegisterType(models.TextChoices):
		COIL = 'COIL', 'Coil (0x)'
		DISCRETE_INPUT = 'DISCRETE', 'Discrete Input (1x)'
		INPUT_REGISTER = 'INPUT', 'Input Register (3x)'
		HOLDING_REGISTER = 'HOLDING', 'Holding Register (4x)'
	
	# Data Types
	class DataType(models.TextChoices):
		INT16 = 'INT16', '16-bit Signed Integer'
		UINT16 = 'UINT16', '16-bit Unsigned Integer'
		INT32 = 'INT32', '32-bit Signed Integer'
		UINT32 = 'UINT32', '32-bit Unsigned Integer'
		FLOAT32 = 'FLOAT32', '32-bit Float'
		FLOAT64 = 'FLOAT64', '64-bit Float'
		STRING = 'STRING', 'ASCII String'
		BOOL = 'BOOL', 'Boolean'
	
	# Byte Order (Endianness)
	class ByteOrder(models.TextChoices):
		BIG_ENDIAN = 'BE', 'Big Endian (AB)'
		LITTLE_ENDIAN = 'LE', 'Little Endian (BA)'
	
	# Word Order for 32-bit values
	class WordOrder(models.TextChoices):
		BIG_ENDIAN = 'BE', 'Big Endian (AB CD)'
		LITTLE_ENDIAN = 'LE', 'Little Endian (CD AB)'
		MID_BIG_ENDIAN = 'MBE', 'Mid-Big Endian (BA DC)'
		MID_LITTLE_ENDIAN = 'MLE', 'Mid-Little Endian (DC BA)'
	
	# Access Modes
	class AccessMode(models.TextChoices):
		READ_ONLY = 'R', 'Read Only'
		READ_WRITE = 'RW', 'Read/Write'
		WRITE_ONLY = 'W', 'Write Only'
	
	# Function Codes
	FUNCTION_CODES = [
		(1, 'Read Coils (0x01)'),
		(2, 'Read Discrete Inputs (0x02)'),
		(3, 'Read Holding Registers (0x03)'),
		(4, 'Read Input Registers (0x04)'),
		(5, 'Write Single Coil (0x05)'),
		(6, 'Write Single Register (0x06)'),
		(15, 'Write Multiple Coils (0x0F)'),
		(16, 'Write Multiple Registers (0x10)'),
	]
	
	slave = models.ForeignKey(SlaveDevice, related_name="registers", on_delete=models.CASCADE)
	name = models.CharField(max_length=64, help_text='Human-readable register name')
	address = models.PositiveIntegerField(validators=[models.validators.MaxValueValidator(65535)])
	register_type = models.CharField(max_length=10, choices=RegisterType.choices, default=RegisterType.HOLDING_REGISTER)
	function_code = models.PositiveSmallIntegerField(choices=FUNCTION_CODES, default=3)
	register_count = models.PositiveSmallIntegerField(default=1, validators=[models.validators.MaxValueValidator(125)])
	enabled = models.BooleanField(default=True)
	preset_register = models.ForeignKey('PresetRegister', on_delete=models.SET_NULL, null=True, blank=True, help_text='Linked preset register')
	
	# Data Interpretation
	data_type = models.CharField(max_length=10, choices=DataType.choices, default=DataType.UINT16)
	byte_order = models.CharField(max_length=10, choices=ByteOrder.choices, default=ByteOrder.BIG_ENDIAN)
	word_order = models.CharField(max_length=10, choices=WordOrder.choices, default=WordOrder.BIG_ENDIAN, blank=True)
	bit_position = models.PositiveSmallIntegerField(null=True, blank=True, validators=[models.validators.MaxValueValidator(15)], help_text='For single bit extraction (0-15)')
	
	# Value Transformation
	scale_factor = models.FloatField(default=1.0, help_text='Multiply raw value by this')
	offset = models.FloatField(default=0.0, help_text='Add this to scaled value')
	formula = models.CharField(max_length=200, blank=True, help_text='Custom formula using x as variable')
	decimal_places = models.PositiveSmallIntegerField(default=2, validators=[models.validators.MaxValueValidator(6)])
	
	# Metadata & Validation
	unit = models.CharField(max_length=20, blank=True, help_text='Engineering unit (V, A, W, etc.)')
	category = models.CharField(max_length=50, blank=True, help_text='Logical grouping')
	min_value = models.FloatField(null=True, blank=True, help_text='Valid range minimum')
	max_value = models.FloatField(null=True, blank=True, help_text='Valid range maximum')
	dead_band = models.FloatField(null=True, blank=True, help_text='Minimum change to report')
	access_mode = models.CharField(max_length=5, choices=AccessMode.choices, default=AccessMode.READ_ONLY)
	
	# Alarm Configuration
	high_alarm_threshold = models.FloatField(null=True, blank=True)
	low_alarm_threshold = models.FloatField(null=True, blank=True)
	
	# Value Mapping for Enums
	value_mapping = models.JSONField(default=dict, blank=True, help_text='Map values to descriptions {"0": "Off", "1": "On"}')
	
	# String Configuration
		string_length = models.PositiveSmallIntegerField(null=True, blank=True, help_text='For ASCII string registers')
	
		# Advanced
		is_signed = models.BooleanField(default=True, help_text='For INT16 vs UINT16 interpretation')
		description = models.TextField(blank=True, help_text='Register description')
	
		class Meta:
			ordering = ["address"]
			indexes = [
				models.Index(fields=["slave", "address"]),
				models.Index(fields=["enabled"]),
			]
	
		def __str__(self):
			return f"{self.slave.slave_id}:{self.name}@{self.address}"
	
		def clean(self):
			if self.min_value is not None and self.max_value is not None:
				if self.min_value >= self.max_value:
					raise ValidationError('Minimum value must be less than maximum value')
	

# Device Preset System for Common Industrial Devices
class DevicePreset(models.Model):
	"""Predefined register mappings for common industrial devices"""
	
	class DeviceType(models.TextChoices):
		SOLAR_INVERTER = 'SOLAR_INV', 'Solar Inverter'
		ENERGY_METER = 'ENERGY_MTR', 'Energy Meter'
		PLC = 'PLC', 'PLC Controller'
		TEMPERATURE_SENSOR = 'TEMP_SENSOR', 'Temperature Sensor'
		FREQUENCY_DRIVE = 'VFD', 'Variable Frequency Drive'
		CUSTOM = 'CUSTOM', 'Custom Device'
	
	name = models.CharField(max_length=100, unique=True)  # e.g., "Solis S6 Inverter"
	manufacturer = models.CharField(max_length=100, blank=True)
	model = models.CharField(max_length=100, blank=True)
	device_type = models.CharField(max_length=20, choices=DeviceType.choices)
	description = models.TextField(blank=True)
	version = models.CharField(max_length=20, default="1.0")
	created_at = models.DateTimeField(default=timezone.now)
	created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
	is_active = models.BooleanField(default=True)
	
	# Default communication settings for this device type
	default_baud_rate = models.PositiveIntegerField(default=9600)
	default_parity = models.CharField(max_length=1, choices=GatewayConfig.ParityType.choices, default=GatewayConfig.ParityType.NONE)
	default_data_bits = models.PositiveSmallIntegerField(default=8)
	default_stop_bits = models.PositiveSmallIntegerField(default=1)
	default_timeout_ms = models.PositiveIntegerField(default=1000)
	default_poll_interval_ms = models.PositiveIntegerField(default=5000)
	
	class Meta:
		ordering = ['manufacturer', 'model']
	
	def __str__(self):
		return f"{self.manufacturer} {self.model}" if self.manufacturer else self.name


class PresetRegister(models.Model):
	"""Register definitions for device presets"""
	preset = models.ForeignKey(DevicePreset, related_name="registers", on_delete=models.CASCADE)
	name = models.CharField(max_length=64)
	address = models.PositiveIntegerField()
	register_type = models.CharField(max_length=10, choices=RegisterMapping.RegisterType.choices)
	function_code = models.PositiveSmallIntegerField(choices=RegisterMapping.FUNCTION_CODES, default=3)
	register_count = models.PositiveSmallIntegerField(default=1)
	data_type = models.CharField(max_length=10, choices=RegisterMapping.DataType.choices, default=RegisterMapping.DataType.UINT16)
	byte_order = models.CharField(max_length=10, choices=RegisterMapping.ByteOrder.choices, default=RegisterMapping.ByteOrder.BIG_ENDIAN)
	word_order = models.CharField(max_length=10, choices=RegisterMapping.WordOrder.choices, default=RegisterMapping.WordOrder.BIG_ENDIAN, blank=True)
	scale_factor = models.FloatField(default=1.0)
	offset = models.FloatField(default=0.0)
	unit = models.CharField(max_length=20, blank=True)
	category = models.CharField(max_length=50, blank=True)
	decimal_places = models.PositiveSmallIntegerField(default=2)
	min_value = models.FloatField(null=True, blank=True)
	max_value = models.FloatField(null=True, blank=True)
	description = models.TextField(blank=True)
	value_mapping = models.JSONField(default=dict, blank=True)
	is_required = models.BooleanField(default=True, help_text='Essential register for this device type')
	display_order = models.PositiveSmallIntegerField(default=100)
	
	class Meta:
		ordering = ['display_order', 'category', 'name']
		unique_together = ('preset', 'address')
	
	def __str__(self):
		return f"{self.preset.name}: {self.name}"


class TelemetryData(models.Model):
	device = models.ForeignKey(Device, related_name="telemetry", on_delete=models.CASCADE)
	timestamp = models.DateTimeField(default=timezone.now)
	data_type = models.CharField(max_length=64)
	value = models.FloatField()
	unit = models.CharField(max_length=16, blank=True, null=True)
	slave_id = models.PositiveSmallIntegerField(blank=True, null=True)
	register_label = models.CharField(max_length=64, blank=True, null=True)
	quality = models.CharField(max_length=16, default="good")

	class Meta:
		indexes = [
			models.Index(fields=["device", "timestamp"]),
			models.Index(fields=["data_type"]),
		]
		ordering = ["-timestamp"]

	def __str__(self):
		return f"{self.device.device_serial}:{self.data_type}={self.value}"


class Alert(models.Model):
	"""Persistent alerts for device monitoring"""
	
	class Severity(models.TextChoices):
		CRITICAL = 'critical', 'Critical'
		WARNING = 'warning', 'Warning'
		INFO = 'info', 'Info'
	
	class Status(models.TextChoices):
		ACTIVE = 'active', 'Active'
		ACKNOWLEDGED = 'acknowledged', 'Acknowledged'
		RESOLVED = 'resolved', 'Resolved'
	
	class AlertType(models.TextChoices):
		DEVICE_OFFLINE = 'device_offline', 'Device Offline'
		LOW_BATTERY = 'low_battery', 'Low Battery'
		HIGH_TEMPERATURE = 'high_temperature', 'High Temperature'
		COMMUNICATION_ERROR = 'communication_error', 'Communication Error'
		THRESHOLD_EXCEEDED = 'threshold_exceeded', 'Threshold Exceeded'
		MAINTENANCE_DUE = 'maintenance_due', 'Maintenance Due'
		CUSTOM = 'custom', 'Custom'
	
	device = models.ForeignKey(Device, related_name="alerts", on_delete=models.CASCADE)
	alert_type = models.CharField(max_length=32, choices=AlertType.choices)
	severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.WARNING)
	status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
	title = models.CharField(max_length=200)
	message = models.TextField()
	triggered_at = models.DateTimeField(default=timezone.now)
	created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="alerts_created")
	acknowledged_at = models.DateTimeField(null=True, blank=True)
	acknowledged_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="acknowledged_alerts")
	resolved_at = models.DateTimeField(null=True, blank=True)
	resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="resolved_alerts")
	metadata = models.JSONField(default=dict, blank=True)  # Store additional context
	
	class Meta:
		ordering = ["-triggered_at"]
		indexes = [
			models.Index(fields=["device", "status"]),
			models.Index(fields=["severity", "status"]),
			models.Index(fields=["triggered_at"]),
		]
	
	def __str__(self):
		return f"{self.device.device_serial}: {self.title} ({self.severity})"
	
	def acknowledge(self, user):
		"""Mark alert as acknowledged"""
		self.status = self.Status.ACKNOWLEDGED
		self.acknowledged_at = timezone.now()
		self.acknowledged_by = user
		self.save(update_fields=["status", "acknowledged_at", "acknowledged_by"])
	
	def resolve(self, user):
		"""Mark alert as resolved"""
		self.status = self.Status.RESOLVED
		self.resolved_at = timezone.now()
		self.resolved_by = user
		self.save(update_fields=["status", "resolved_at", "resolved_by"])
