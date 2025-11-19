from django.contrib import admin
from .models import (
	Device,
	GatewayConfig,
	SlaveDevice,
	RegisterMapping,
	TelemetryData,
)


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
	list_display = ("device_serial", "provisioned_at", "config_version")
	search_fields = ("device_serial",)


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
