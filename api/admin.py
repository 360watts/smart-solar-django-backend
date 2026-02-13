from django.contrib import admin
from django.contrib.auth.models import User
from .models import (
	Device,
	GatewayConfig,
	SlaveDevice,
	RegisterMapping,
	TelemetryData,
	Customer,
)


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
	list_display = ("device_serial", "customer", "provisioned_at", "config_version")
	search_fields = ("device_serial", "customer__customer_id", "customer__first_name", "customer__last_name")
	list_filter = ("provisioned_at",)


@admin.register(Customer)
class UserAdmin(admin.ModelAdmin):
	list_display = ("customer_id", "first_name", "last_name", "email", "mobile_number", "created_at", "is_active")
	search_fields = ("customer_id", "first_name", "last_name", "email", "mobile_number")
	list_filter = ("is_active", "created_at")
	readonly_fields = ("created_at",)
	fieldsets = (
		("Customer Information", {
			"fields": ("customer_id", "first_name", "last_name", "email")
		}),
		("Contact Details", {
			"fields": ("mobile_number", "address")
		}),
		("Status", {
			"fields": ("is_active",)
		}),
		("Additional", {
			"fields": ("notes", "created_at"),
			"classes": ("collapse",)
		}),
	)


# Unregister default User admin and register custom one
admin.site.unregister(User)


@admin.register(User)
class EmployeeAdmin(admin.ModelAdmin):
	list_display = ("username", "first_name", "last_name", "email", "is_staff", "is_superuser", "date_joined")
	search_fields = ("username", "first_name", "last_name", "email")
	list_filter = ("is_staff", "is_superuser", "is_active", "date_joined")
	readonly_fields = ("date_joined", "last_login")
	fieldsets = (
		("Login Information", {
			"fields": ("username", "password"),
		}),
		("Personal Information", {
			"fields": ("first_name", "last_name", "email")
		}),
		("Permissions", {
			"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions"),
			"classes": ("wide",)
		}),
		("Important Dates", {
			"fields": ("date_joined", "last_login"),
			"classes": ("collapse",)
		}),
	)
	filter_horizontal = ("groups", "user_permissions")
	
	def get_queryset(self, request):
		"""Show all staff users (employees) in the list"""
		qs = super().get_queryset(request)
		return qs.filter(is_staff=True)




class RegisterMappingInline(admin.TabularInline):
	model = RegisterMapping
	extra = 0


@admin.register(GatewayConfig)
class GatewayConfigAdmin(admin.ModelAdmin):
	list_display = ("config_id", "name", "updated_at", "baud_rate", "parity", "slave_count")
	filter_horizontal = ("slaves",)  # M2M widget for selecting slaves
	search_fields = ("config_id", "name")
	
	def slave_count(self, obj):
		return obj.slaves.count()
	slave_count.short_description = "Slaves"


@admin.register(SlaveDevice)
class SlaveDeviceAdmin(admin.ModelAdmin):
	list_display = ("slave_id", "device_name", "polling_interval_ms", "timeout_ms", "enabled", "preset_count")
	inlines = [RegisterMappingInline]
	list_filter = ("enabled",)
	search_fields = ("device_name",)
	
	def preset_count(self, obj):
		return obj.presets.count()
	preset_count.short_description = "Used in Presets"


@admin.register(TelemetryData)
class TelemetryDataAdmin(admin.ModelAdmin):
	list_display = ("device", "timestamp", "data_type", "value", "unit")
	list_filter = ("data_type", "timestamp")
	search_fields = ("device__device_serial", "data_type", "register_label")
