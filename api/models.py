from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class UserProfile(models.Model):
    """
    User profile for all users with role hierarchy:
    - MASTER: Superuser with all rights
    - ADMIN: Staff/installers who manage the web application
    - USER: Device owners who will use the Android mobile application
    """
    USER_TYPE_CHOICES = [
        ('MASTER', 'Master'),
        ('ADMIN', 'Admin'),
        ('USER', 'User'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    user_type = models.CharField(
        max_length=10, 
        choices=USER_TYPE_CHOICES, 
        default='USER',
        help_text='Master: All rights, Admin: Staff/installers, User: Device owners'
    )
    mobile_number = models.CharField(max_length=15, blank=True, null=True)
    address = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.user.username}'s profile ({self.get_user_type_display()})"


@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    """
    Auto-create UserProfile for new users and set user_type based on permissions
    """
    if created:
        # Determine user_type based on Django permissions
        if instance.is_superuser:
            user_type = 'MASTER'
        elif instance.is_staff:
            user_type = 'ADMIN'
        else:
            user_type = 'USER'
        
        UserProfile.objects.create(user=instance, user_type=user_type)
    else:
        # Update existing profile's user_type if permissions changed
        try:
            profile = instance.userprofile
            if instance.is_superuser and profile.user_type != 'MASTER':
                profile.user_type = 'MASTER'
                profile.save()
            elif instance.is_staff and not instance.is_superuser and profile.user_type != 'ADMIN':
                profile.user_type = 'ADMIN'
                profile.save()
        except UserProfile.DoesNotExist:
            # Create profile if it doesn't exist
            user_type = 'MASTER' if instance.is_superuser else ('ADMIN' if instance.is_staff else 'USER')
            UserProfile.objects.create(user=instance, user_type=user_type)


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


class GatewayConfig(models.Model):
	"""
	Device preset configuration.
	Contains UART settings and references to slave devices.
	"""
	config_id = models.CharField(max_length=64, unique=True)
	name = models.CharField(max_length=100, blank=True, default='')
	created_at = models.DateTimeField(default=timezone.now)
	created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='gateway_configs_created')
	updated_at = models.DateTimeField(auto_now=True)
	updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='gateway_configs_updated')
	config_schema_ver = models.PositiveIntegerField(default=1)
	baud_rate = models.PositiveIntegerField(default=9600)
	data_bits = models.PositiveSmallIntegerField(default=8)
	stop_bits = models.PositiveSmallIntegerField(default=1)
	parity = models.PositiveSmallIntegerField(default=0)  # 0=None,1=Odd,2=Even
	# ManyToMany relationship to SlaveDevice - presets reference global slaves
	slaves = models.ManyToManyField('SlaveDevice', related_name='presets', blank=True)

	def __str__(self):
		return self.name or self.config_id


class Device(models.Model):
	device_serial = models.CharField(max_length=64, unique=True)
	customer = models.ForeignKey(Customer, related_name="devices", on_delete=models.CASCADE)
	# Link to device preset configuration
	gateway_config = models.ForeignKey(GatewayConfig, related_name="devices", on_delete=models.SET_NULL, null=True, blank=True)
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




class SlaveDevice(models.Model):
	"""
	Global slave device configuration. 
	Slaves are created independently in the Configuration page.
	Presets reference slaves via ManyToMany relationship.
	"""
	slave_id = models.PositiveSmallIntegerField()
	device_name = models.CharField(max_length=64)
	polling_interval_ms = models.PositiveIntegerField(default=5000)
	timeout_ms = models.PositiveIntegerField(default=1000)
	enabled = models.BooleanField(default=True)
	created_at = models.DateTimeField(default=timezone.now)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		unique_together = []  # slave_id no longer needs to be unique per config
		ordering = ["slave_id"]

	def __str__(self):
		return f"slave:{self.slave_id}:{self.device_name}"


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
