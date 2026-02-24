from django.urls import path
from . import views

urlpatterns = [
    # OTA device check endpoint (main endpoint for STM32)
    path('devices/<str:device_id>/check', views.ota_check, name='ota_check'),
    
    # Firmware download
    path('firmware/<int:firmware_id>/download', views.ota_download, name='ota_download'),
    
    # Update logs and history
    path('devices/<str:device_id>/logs', views.device_update_logs, name='device_update_logs'),
    
    # Firmware management
    path('firmware/', views.firmware_versions_list, name='firmware_list'),
    path('firmware/create/', views.create_firmware_version, name='create_firmware'),
    path('firmware/<int:firmware_id>/', views.update_firmware_version, name='update_firmware'),
    path('firmware/<int:firmware_id>/delete/', views.delete_firmware_version, name='delete_firmware'),
    
    # Configuration
    path('config/', views.get_ota_config, name='get_ota_config'),
    path('config/update/', views.update_ota_config, name='update_ota_config'),
    
    # Targeted OTA Updates - Three methods
    path('updates/single/', views.trigger_single_device_update, name='trigger_single_update'),
    path('updates/multiple/', views.trigger_multi_device_update, name='trigger_multi_update'),
    path('updates/version-based/', views.trigger_version_based_update, name='trigger_version_update'),
    path('updates/rollback/', views.trigger_rollback, name='trigger_rollback'),
    path('updates/', views.list_targeted_updates, name='list_targeted_updates'),
    path('updates/<int:update_id>/', views.get_targeted_update, name='get_targeted_update'),
    path('updates/<int:update_id>/cancel/', views.cancel_targeted_update, name='cancel_targeted_update'),
    
    # Device firmware versions (for version-based update selection)
    path('device-versions/', views.get_device_firmware_versions, name='device_firmware_versions'),
    
    # Health check
    path('health/', views.ota_health, name='ota_health'),
]
