from django.contrib import admin
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
class CustomerAdmin(admin.ModelAdmin):
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



class RegisterMappingInline(admin.TabularInline):
	model = RegisterMapping
	extra = 0


class SlaveDeviceInline(admin.TabularInline):
	model = SlaveDevice
	extra = 0


@admin.register(GatewayConfig)
class GatewayConfigAdmin(admin.ModelAdmin):
	list_display = ("config_id", "updated_at", "baud_rate", "parity")
	inlines = [SlaveDeviceInline]
	search_fields = ("config_id",)


@admin.register(SlaveDevice)
class SlaveDeviceAdmin(admin.ModelAdmin):
	list_display = ("gateway_config", "slave_id", "device_name", "enabled")
	inlines = [RegisterMappingInline]
	list_filter = ("gateway_config", "enabled")


@admin.register(TelemetryData)
class TelemetryDataAdmin(admin.ModelAdmin):
	list_display = ("device", "timestamp", "data_type", "value", "unit")
	list_filter = ("data_type", "timestamp")
	search_fields = ("device__device_serial", "data_type", "register_label")
