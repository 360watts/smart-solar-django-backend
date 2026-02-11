"""
Simple direct check - bypass view and check what devices exist
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

from api.models import Device

devices = Device.objects.select_related('customer', 'user', 'created_by', 'updated_by').all().order_by("-provisioned_at")[:3]

print(f"Total devices in DB: {Device.objects.count()}")
print(f"\n=== Latest 3 Devices ===\n")

for device in devices:
    print(f"Serial: {device.device_serial}")
    print(f"  Customer: {device.customer.customer_id if device.customer else 'None'}")
    print(f"  Created By: {device.created_by.username if device.created_by else 'NULL'}")
    print(f"  Updated By: {device.updated_by.username if device.updated_by else 'NULL'}")
    print(f"  Updated At: {device.updated_at}")
    print()
