from django.contrib import admin
from django.contrib.auth.models import User
from .models import (
	Device,
	GatewayConfig,
	SlaveDevice,
	RegisterMapping,
	TelemetryData,
	UserProfile,
)


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
	list_display = ("device_serial", "owner", "provisioned_at", "config_version")
	search_fields = ("device_serial", "owner__username", "owner__email")
	list_filter = ("provisioned_at",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
	list_display = ("user", "role", "mobile_number", "created_at")
	search_fields = ("user__username", "user__email", "mobile_number")
	list_filter = ("role", "created_at")
	readonly_fields = ("created_at",)


# Unregister default User admin and register custom one
admin.site.unregister(User)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
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
