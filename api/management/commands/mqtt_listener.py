import json
import time
from django.core.management.base import BaseCommand
from django.utils import timezone
import paho.mqtt.client as mqtt
from api.serializers import TelemetryIngestSerializer

# Simple MQTT listener subscribing to all telemetry topics:
# devices/+/telemetry/#
# Expects JSON payload as documented in firmware.

BROKER_URI = "localhost"  # adjust to broker host/IP
BROKER_PORT = 1883
TOPIC = "devices/+/telemetry/#"

class Command(BaseCommand):
    help = "Run MQTT telemetry listener and store incoming messages"

    def add_arguments(self, parser):
        parser.add_argument("--host", default=BROKER_URI)
        parser.add_argument("--port", type=int, default=BROKER_PORT)

    def handle(self, *args, **options):
        host = options["host"]
        port = options["port"]

        client = mqtt.Client()

        def on_connect(cl, userdata, flags, rc):
            if rc == 0:
                self.stdout.write(self.style.SUCCESS(f"Connected to MQTT broker {host}:{port}"))
                cl.subscribe(TOPIC, qos=1)
            else:
                self.stdout.write(self.style.ERROR(f"MQTT connection failed rc={rc}"))

        def on_message(cl, userdata, msg):
            try:
                payload = json.loads(msg.payload.decode("utf-8"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Invalid JSON on {msg.topic}: {e}"))
                return
            # Ensure timestamp
            if "timestamp" not in payload:
                payload["timestamp"] = timezone.now().isoformat()
            serializer = TelemetryIngestSerializer(data=payload)
            if serializer.is_valid():
                telemetry = serializer.save()
                self.stdout.write(
                    f"Stored telemetry: device={payload.get('deviceId')} type={payload.get('dataType')} value={payload.get('value')} id={telemetry.id}"
                )
            else:
                self.stdout.write(self.style.WARNING(f"Telemetry validation failed: {serializer.errors}"))

        client.on_connect = on_connect
        client.on_message = on_message
        client.connect(host, port, 60)
        client.loop_start()
        self.stdout.write("MQTT listener started. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stdout.write("Stopping MQTT listener...")
            client.loop_stop()
            client.disconnect()
