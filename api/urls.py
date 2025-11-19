from django.urls import path
from . import views


urlpatterns = [
	path("devices/provision", views.provision, name="provision"),
	path("devices/<str:device_id>/config", views.gateway_config, name="gateway_config"),
	path("devices/<str:device_id>/heartbeat", views.heartbeat, name="heartbeat"),
	path("devices/<str:device_id>/logs", views.logs, name="logs"),
	path("telemetry/ingest", views.telemetry_ingest, name="telemetry_ingest"),
	path("devices/<str:device_serial>/telemetry/latest", views.telemetry_latest, name="telemetry_latest"),
]