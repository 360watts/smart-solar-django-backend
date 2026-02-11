"""
Show the difference between auto-provisioned and manually created devices
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

from api.models import Device

print("=== ESP32 AUTO-PROVISIONED DEVICES (customer = UNASSIGNED) ===")
auto_devices = Device.objects.filter(customer__customer_id="UNASSIGNED").select_related('created_by', 'updated_by')[:5]
print(f"Total: {auto_devices.count()}\n")
for d in auto_devices:
    print(f"{d.device_serial} | Created by: {d.created_by.username if d.created_by else 'NULL'} | Customer: {d.customer.customer_id}")

print("\n=== MANUALLY CREATED DEVICES (customer = DEFAULT) ===")
manual_devices = Device.objects.filter(customer__customer_id="DEFAULT").select_related('created_by', 'updated_by')[:5]
print(f"Total: {manual_devices.count()}\n")
if manual_devices.exists():
    for d in manual_devices:
        print(f"{d.device_serial} | Created by: {d.created_by.username if d.created_by else 'NULL'} | Customer: {d.customer.customer_id}")
else:
    print("No manually created devices yet. Use 'Register New Device' button in UI to create one.")

print("\n💡 TIP: Devices with customer='UNASSIGNED' are auto-provisioned by ESP32 hardware")
print("     Devices with customer='DEFAULT' are manually registered through the web UI")
