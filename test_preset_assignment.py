"""
Test device preset assignment
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

from api.models import Device, GatewayConfig
from django.contrib.auth.models import User

print("=" * 60)
print("Testing Device Preset Assignment")
print("=" * 60)

# Get a device
device = Device.objects.first()
if not device:
    print("No devices found!")
    exit(1)

print(f"\n1. Current device state:")
print(f"   Device: {device.device_serial}")
print(f"   Gateway Config ID: {device.gateway_config.id if device.gateway_config else None}")
print(f"   Gateway Config Name: {device.gateway_config.name if device.gateway_config else None}")

# Get a preset
preset = GatewayConfig.objects.first()
if not preset:
    print("\n   No presets found! Creating a test preset...")
    from django.utils import timezone
    preset = GatewayConfig.objects.create(
        config_id='TEST_PRESET',
        name='Test Preset',
        baud_rate=9600,
        data_bits=8,
        stop_bits=1,
        parity=0
    )
    print(f"   Created preset: {preset.name}")

print(f"\n2. Assigning preset '{preset.name}' (ID: {preset.id}) to device...")
device.gateway_config = preset
device.save()
print(f"   ✓ Preset assigned")

# Re-fetch device to verify
device.refresh_from_db()
print(f"\n3. Verifying assignment:")
print(f"   Device: {device.device_serial}")
print(f"   Gateway Config ID: {device.gateway_config.id if device.gateway_config else None}")
print(f"   Gateway Config Name: {device.gateway_config.name if device.gateway_config else None}")

if device.gateway_config and device.gateway_config.id == preset.id:
    print(f"\n   ✓ SUCCESS: Preset correctly assigned!")
else:
    print(f"\n   ✗ FAILED: Preset not assigned correctly")

# Now test via serializer
print(f"\n4. Testing via DeviceSerializer...")
from api.serializers import DeviceSerializer

update_data = {
    'gateway_config_id': preset.id
}

serializer = DeviceSerializer(device, data=update_data, partial=True)
if serializer.is_valid():
    updated_device = serializer.save()
    print(f"   ✓ Serializer update successful")
    print(f"   Gateway Config ID: {updated_device.gateway_config.id if updated_device.gateway_config else None}")
    print(f"   Gateway Config Name: {updated_device.gateway_config.name if updated_device.gateway_config else None}")
else:
    print(f"   ✗ Serializer validation failed: {serializer.errors}")

# Test clearing the preset (setting to null)
print(f"\n5. Testing preset removal (setting to null)...")
update_data = {
    'gateway_config_id': None
}

serializer = DeviceSerializer(device, data=update_data, partial=True)
if serializer.is_valid():
    updated_device = serializer.save()
    updated_device.refresh_from_db()
    print(f"   ✓ Serializer update successful")
    print(f"   Gateway Config ID: {updated_device.gateway_config.id if updated_device.gateway_config else None}")
    print(f"   Gateway Config Name: {updated_device.gateway_config.name if updated_device.gateway_config else 'None (successfully cleared)'}")
else:
    print(f"   ✗ Serializer validation failed: {serializer.errors}")

print("=" * 60)
