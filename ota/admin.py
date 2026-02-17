from django.contrib import admin
from .models import FirmwareVersion, DeviceUpdateLog, OTAConfig


@admin.register(FirmwareVersion)
class FirmwareVersionAdmin(admin.ModelAdmin):
    list_display = ['version', 'filename', 'size', 'is_active', 'created_at', 'created_by']
    list_filter = ['is_active', 'created_at']
    search_fields = ['version', 'filename', 'description']
    readonly_fields = ['created_at', 'updated_at', 'created_by', 'updated_by']
    
    fieldsets = (
        ('Version Info', {
            'fields': ('version', 'filename', 'file', 'size', 'checksum')
        }),
        ('Details', {
            'fields': ('description', 'release_notes')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'created_by', 'updated_at', 'updated_by'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        if not change:  # Creating new
            obj.created_by = request.user
        obj.updated_by = request.user
        
        # Calculate file size if not set
        if obj.file and not obj.size:
            obj.size = obj.file.size
        
        super().save_model(request, obj, form, change)


@admin.register(DeviceUpdateLog)
class DeviceUpdateLogAdmin(admin.ModelAdmin):
    list_display = ['device', 'firmware_version', 'status', 'bytes_downloaded', 'last_checked_at']
    list_filter = ['status', 'last_checked_at']
    search_fields = ['device__device_serial', 'firmware_version__version']
    readonly_fields = ['device', 'bytes_downloaded', 'started_at', 'completed_at', 'last_checked_at']
    
    fieldsets = (
        ('Device Info', {
            'fields': ('device', 'current_firmware')
        }),
        ('Update Info', {
            'fields': ('firmware_version', 'status', 'bytes_downloaded', 'attempt_count')
        }),
        ('Timestamps', {
            'fields': ('started_at', 'completed_at', 'last_checked_at'),
            'classes': ('collapse',)
        }),
        ('Error Details', {
            'fields': ('error_message',),
            'classes': ('collapse',)
        }),
    )


@admin.register(OTAConfig)
class OTAConfigAdmin(admin.ModelAdmin):
    list_display = ['enable_auto_update', 'update_strategy', 'max_concurrent_updates']
    
    fieldsets = (
        ('Update Strategy', {
            'fields': ('enable_auto_update', 'update_strategy', 'max_concurrent_updates')
        }),
        ('Maintenance', {
            'fields': ('firmware_retention_days',)
        }),
        ('Metadata', {
            'fields': ('updated_at', 'updated_by'),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        # Only allow one OTA config
        return OTAConfig.objects.count() == 0
    
    def has_delete_permission(self, request, obj=None):
        # Don't allow deletion of OTA config
        return False
    
    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
