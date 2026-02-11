import os
import django
from decouple import config

# Set up environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

from api.models import Device, User

print("=== Device Records with Audit Trail ===\n")

devices = Device.objects.all().select_related('customer', 'created_by', 'updated_by')

if not devices.exists():
    print("No devices found in database.")
else:
    for device in devices:
        print(f"Device: {device.device_serial}")
        print(f"  Customer: {device.customer}")
        print(f"  Provisioned At: {device.provisioned_at}")
        print(f"  Created By: {device.created_by.username if device.created_by else 'NULL'}")
        print(f"  Updated By: {device.updated_by.username if device.updated_by else 'NULL'}")
        print(f"  Updated At: {device.updated_at}")
        print()

print(f"\nTotal devices: {devices.count()}")
print(f"Devices with created_by: {devices.exclude(created_by=None).count()}")
print(f"Devices with updated_by: {devices.exclude(updated_by=None).count()}")

print("\n=== Available Users ===")
users = User.objects.all()
for user in users:
    print(f"  - {user.username} (ID: {user.id}, Staff: {user.is_staff})")
