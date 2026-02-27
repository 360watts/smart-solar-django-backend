from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.conf import settings


class UserProfile(models.Model):
    """Profile for all users — role distinguishes admin, employee, and user"""

    class Role(models.TextChoices):
        ADMIN    = 'admin',    'Admin'
        EMPLOYEE = 'employee', 'Employee'
        USER     = 'user',     'User'

    user          = models.OneToOneField(User, on_delete=models.CASCADE)
    role          = models.CharField(max_length=16, choices=Role.choices, default=Role.USER)
    mobile_number = models.CharField(max_length=15, blank=True, null=True)
    address       = models.TextField(blank=True, null=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username}'s profile"




class Device(models.Model):
	device_serial = models.CharField(max_length=64, unique=True)
	hw_id = models.CharField(max_length=64, blank=True, null=True, help_text="MAC address or hardware ID sent at provisioning")
	model = models.CharField(max_length=64, blank=True, null=True, help_text="Device model string sent at provisioning")
	user = models.ForeignKey(User, related_name="devices", on_delete=models.SET_NULL, null=True, blank=True)
	public_key_algorithm = models.CharField(max_length=32, blank=True, null=True)
	csr_pem = models.TextField(blank=True, null=True)
	provisioned_at = models.DateTimeField(default=timezone.now)
	config_version = models.CharField(max_length=32, blank=True, null=True)
	config_ack_ver = models.PositiveIntegerField(null=True, blank=True, help_text="Last config version acknowledged by device via /configAck")
	config_downloaded_at = models.DateTimeField(null=True, blank=True, help_text="Last time device downloaded config from /config endpoint")
	config_acked_at = models.DateTimeField(null=True, blank=True, help_text="Last time device acknowledged config via /configAck endpoint")
	last_heartbeat = models.DateTimeField(null=True, blank=True, help_text="Last time device sent a heartbeat")
	pending_reboot = models.BooleanField(default=False, help_text="Flag to trigger device reboot on next heartbeat")
	pending_hard_reset = models.BooleanField(default=False, help_text="Flag to trigger device hard reset on next heartbeat")
	pending_rollback = models.BooleanField(default=False, help_text="Flag to trigger firmware rollback on next heartbeat")
	pending_config_update = models.BooleanField(default=False, help_text="Set when preset/slave changes so device fetches config on next heartbeat")
	logs_enabled = models.BooleanField(default=False, help_text="Enable device to send logs")
	created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='devices_created')
	updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='devices_updated')
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		indexes = [
			models.Index(fields=['user']),
			models.Index(fields=['config_version']),
			models.Index(fields=['last_heartbeat']),
		]

	def __str__(self):
		return self.device_serial

	def is_online(self):
		"""Check if device is online based on last heartbeat."""
		if not self.last_heartbeat:
			return False
		timeout = getattr(settings, 'DEVICE_HEARTBEAT_TIMEOUT_SECONDS', 300)
		return (timezone.now() - self.last_heartbeat).total_seconds() < timeout


class GatewayConfig(models.Model):
	config_id = models.CharField(max_length=64, unique=True)
	name = models.CharField(max_length=100, blank=True, default='')
	version = models.PositiveIntegerField(default=1, help_text="Incremented on every config or slave change — used for cfgVer in device protocol")
	created_at = models.DateTimeField(default=timezone.now)
	created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='gateway_configs_created')
	updated_at = models.DateTimeField(auto_now=True)
	updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='gateway_configs_updated')
	config_schema_ver = models.PositiveIntegerField(default=1)
	baud_rate = models.PositiveIntegerField(default=9600)
	data_bits = models.PositiveSmallIntegerField(default=8)
	stop_bits = models.PositiveSmallIntegerField(default=1)
	parity = models.PositiveSmallIntegerField(default=0)  # 0=None,1=Odd,2=Even

	def __str__(self):
		return self.name or self.config_id


class SlaveDevice(models.Model):
	# Allow slaves to exist without being attached to a GatewayConfig (global mode)
	gateway_config = models.ForeignKey(GatewayConfig, related_name="slaves", on_delete=models.CASCADE, null=True, blank=True)
	slave_id = models.PositiveSmallIntegerField()
	device_name = models.CharField(max_length=64)
	polling_interval_ms = models.PositiveIntegerField(default=5000)
	timeout_ms = models.PositiveIntegerField(default=1000)
	priority = models.PositiveSmallIntegerField(default=1)  # 1=Highest, 10=Lowest
	enabled = models.BooleanField(default=True)

	class Meta:
		unique_together = ("gateway_config", "slave_id")
		ordering = ["slave_id"]

	def __str__(self):
		cfg = self.gateway_config.config_id if self.gateway_config else 'global'
		return f"{cfg}:slave:{self.slave_id}"


class RegisterMapping(models.Model):
	slave = models.ForeignKey(SlaveDevice, related_name="registers", on_delete=models.CASCADE)
	label = models.CharField(max_length=64)
	address = models.PositiveIntegerField()
	num_registers = models.PositiveSmallIntegerField(default=1)
	function_code = models.PositiveSmallIntegerField(default=3)
	register_type = models.PositiveSmallIntegerField(default=3)  # 0=Coil,1=Discrete Input,2=Input Reg,3=Holding Reg
	data_type = models.PositiveSmallIntegerField(default=0)  # 0=UINT16,1=INT16,2=UINT32,3=INT32,4=FLOAT32,5=UINT64,6=INT64,7=FLOAT64,8=BOOL,9=STRING
	byte_order = models.PositiveSmallIntegerField(default=0)  # 0=Big Endian (ABCD),1=Little Endian (DCBA)
	word_order = models.PositiveSmallIntegerField(default=0)  # 0=Big (AB CD),1=Little (CD AB),2=Mid-Big (BA DC),3=Mid-Little (DC BA)
	access_mode = models.PositiveSmallIntegerField(default=0)  # 0=Read Only,1=Read/Write,2=Write Only
	scale_factor = models.FloatField(default=1.0)
	offset = models.FloatField(default=0.0)
	unit = models.CharField(max_length=16, blank=True, null=True)
	decimal_places = models.PositiveSmallIntegerField(default=2)
	category = models.CharField(max_length=32, blank=True, null=True)  # Electrical,Temperature,Status,Control,Energy,Power,Other
	high_alarm_threshold = models.FloatField(null=True, blank=True)
	low_alarm_threshold = models.FloatField(null=True, blank=True)
	description = models.TextField(blank=True, null=True)
	enabled = models.BooleanField(default=True)

	class Meta:
		ordering = ["address"]

	def __str__(self):
		return f"{self.slave.slave_id}:{self.label}@{self.address}"


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


class DeviceLog(models.Model):
	"""Store logs received from devices"""
	device = models.ForeignKey(Device, related_name="logs", on_delete=models.CASCADE)
	timestamp = models.DateTimeField(default=timezone.now)
	log_level = models.CharField(max_length=16, default="INFO")  # DEBUG, INFO, WARNING, ERROR, CRITICAL
	message = models.TextField()
	metadata = models.JSONField(default=dict, blank=True)  # Store additional context
	
	class Meta:
		ordering = ["-timestamp"]
		indexes = [
			models.Index(fields=["device", "timestamp"]),
			models.Index(fields=["log_level"]),
		]
	
	def __str__(self):
		return f"{self.device.device_serial} [{self.log_level}] {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"


class SolarSite(models.Model):
    """Solar installation details for a device/customer site.
    Table already created in Supabase via raw SQL — managed=False."""
    device       = models.OneToOneField(Device, on_delete=models.CASCADE,
                                        related_name='solar_site', db_column='device_id')
    site_id      = models.CharField(max_length=64, unique=True)
    display_name = models.CharField(max_length=100, blank=True)
    latitude     = models.FloatField()
    longitude    = models.FloatField()
    capacity_kw  = models.FloatField()
    tilt_deg     = models.FloatField(default=18.0)
    azimuth_deg  = models.FloatField(default=180.0)
    timezone     = models.CharField(max_length=50, default='Asia/Kolkata')
    is_active    = models.BooleanField(default=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False          # table already exists in Supabase — no migration needed
        db_table = 'api_solarsite'

    def __str__(self):
        return f"{self.site_id} ({self.device.device_serial})"
