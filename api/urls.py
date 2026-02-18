from django.urls import path, include
from . import views
from rest_framework_simplejwt.views import TokenRefreshView


urlpatterns = [
	path("devices/provision", views.provision, name="provision"),
	path("devices/<str:device_id>/config", views.gateway_config, name="gateway_config"),
	path("devices/<str:device_id>/heartbeat", views.heartbeat, name="heartbeat"),
	path("devices/<str:device_id>/logs", views.logs, name="logs"),
	path("telemetry/ingest", views.telemetry_ingest, name="telemetry_ingest"),
	path("devices/<str:device_serial>/telemetry/latest", views.telemetry_latest, name="telemetry_latest"),
	path("devices/", views.devices_list, name="devices_list"),
	path("config/", views.config_get, name="config_get"),
	path("telemetry/", views.telemetry_all, name="telemetry_all"),
	path("alerts/", views.alerts_list, name="alerts_list"),
	path("health/", views.system_health, name="system_health"),
	path("kpis/", views.kpis, name="kpis"),
	path("auth/register/", views.register_user, name="register_user"),
	path("auth/login/", views.login_user, name="login_user"),
	path("auth/logout/", views.logout_user, name="logout_user"),
	path("auth/user/", views.get_current_user, name="get_current_user"),
	path("auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
	path("users/", views.users_list, name="users_list"),
	path("users/create/", views.create_user, name="create_user"),
	path("users/<int:user_id>/", views.update_user, name="update_user"),
	path("users/<int:user_id>/delete/", views.delete_user, name="delete_user"),
	path("users/<int:user_id>/devices/", views.get_user_devices, name="get_user_devices"),
	
	# Profile management endpoints (for current logged-in user)
	path("profile/", views.get_profile, name="get_profile"),
	path("profile/update/", views.update_profile, name="update_profile"),
	path("profile/change-password/", views.change_password, name="change_password"),
	
	path("presets/", views.presets_list, name="presets_list"),
	path("presets/create/", views.create_preset, name="create_preset"),
	path("presets/<int:preset_id>/", views.update_preset, name="update_preset"),
	path("presets/<int:preset_id>/delete/", views.delete_preset, name="delete_preset"),
	path("devices/create/", views.create_device, name="create_device"),
	path("devices/<int:device_id>/", views.update_device, name="update_device"),
	path("devices/<int:device_id>/delete/", views.delete_device, name="delete_device"),
	path("devices/delete-bulk/", views.delete_devices_bulk, name="delete_devices_bulk"),
	path("presets/<str:config_id>/slaves/", views.slaves_list, name="slaves_list"),
	path("presets/<str:config_id>/slaves/create/", views.create_slave, name="create_slave"),
	path("presets/<str:config_id>/slaves/<int:slave_id>/", views.update_slave, name="update_slave"),
	path("presets/<str:config_id>/slaves/<int:slave_id>/delete/", views.delete_slave, name="delete_slave"),
	
	# Alert management endpoints (persistent alerts)
	path("alerts/manage/", views.alerts_crud, name="alerts_crud"),
	path("alerts/<int:alert_id>/", views.alert_detail, name="alert_detail"),
	path("alerts/<int:alert_id>/acknowledge/", views.alert_acknowledge, name="alert_acknowledge"),
	path("alerts/<int:alert_id>/resolve/", views.alert_resolve, name="alert_resolve"),
	
	# OTA Update endpoints
	path("ota/", include("ota.urls")),
]