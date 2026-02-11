"""
Check the most recent devices to see their created_by values
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

from api.models import Device, User

print("=== Most Recent 5 Devices ===\n")

devices = Device.objects.all().select_related('customer', 'created_by', 'updated_by').order_by('-provisioned_at')[:5]

for device in devices:
    print(f"Device: {device.device_serial}")
    print(f"  Provisioned At: {device.provisioned_at}")
    print(f"  Created By: {device.created_by.username if device.created_by else 'NULL'} (ID: {device.created_by.id if device.created_by else 'N/A'})")
    print(f"  Updated By: {device.updated_by.username if device.updated_by else 'NULL'} (ID: {device.updated_by.id if device.updated_by else 'N/A'})")
    print(f"  Customer: {device.customer.customer_id}")
    print()

print("\n=== Check if 'system' user exists ===")
try:
    system_user = User.objects.get(username="system")
    print(f"System user found: ID={system_user.id}, Email={system_user.email}")
except User.DoesNotExist:
    print("System user does NOT exist in database")

print("\n=== All Users ===")
users = User.objects.all()
for user in users:
    print(f"  {user.username} (ID: {user.id})")
