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
    
    # Configuration
    path('config/', views.get_ota_config, name='get_ota_config'),
    path('config/update/', views.update_ota_config, name='update_ota_config'),
    
    # Health check
    path('health/', views.ota_health, name='ota_health'),
]
