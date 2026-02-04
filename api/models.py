from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User


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

	def __str__(self):
		return self.device_serial


class GatewayConfig(models.Model):
	config_id = models.CharField(max_length=64, unique=True)
	name = models.CharField(max_length=100, blank=True, default='')
	updated_at = models.DateTimeField(default=timezone.now)
	config_schema_ver = models.PositiveIntegerField(default=1)
	baud_rate = models.PositiveIntegerField(default=9600)
	data_bits = models.PositiveSmallIntegerField(default=8)
	stop_bits = models.PositiveSmallIntegerField(default=1)
	parity = models.PositiveSmallIntegerField(default=0)  # 0=None,1=Odd,2=Even

	def __str__(self):
		return self.name or self.config_id


class SlaveDevice(models.Model):
	gateway_config = models.ForeignKey(GatewayConfig, related_name="slaves", on_delete=models.CASCADE)
	slave_id = models.PositiveSmallIntegerField()
	device_name = models.CharField(max_length=64)
	polling_interval_ms = models.PositiveIntegerField(default=5000)
	timeout_ms = models.PositiveIntegerField(default=1000)
	enabled = models.BooleanField(default=True)

	class Meta:
		unique_together = ("gateway_config", "slave_id")
		ordering = ["slave_id"]

	def __str__(self):
		return f"{self.gateway_config.config_id}:slave:{self.slave_id}"


class RegisterMapping(models.Model):
	slave = models.ForeignKey(SlaveDevice, related_name="registers", on_delete=models.CASCADE)
	label = models.CharField(max_length=64)
	address = models.PositiveIntegerField()
	num_registers = models.PositiveSmallIntegerField(default=1)
	function_code = models.PositiveSmallIntegerField(default=3)
	data_type = models.PositiveSmallIntegerField(default=0)  # see doc mapping
	scale_factor = models.FloatField(default=1.0)
	offset = models.FloatField(default=0.0)
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
