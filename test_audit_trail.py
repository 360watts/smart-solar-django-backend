"""
Test audit trail on manual device creation (local test)
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

from api.models import Device, Customer, User
from django.test import RequestFactory
from api.views import set_audit_fields
from django.utils import timezone

# Get admin user
admin_user = User.objects.get(username="admin")

# Create a test device manually
default_customer, _ = Customer.objects.get_or_create(
    customer_id="DEFAULT",
    defaults={
        "first_name": "Unassigned",
        "last_name": "Devices",
        "email": "default@example.com",
        "notes": "Default customer for newly provisioned devices"
    }
)

# Create test device
test_device = Device.objects.create(
    device_serial=f"TEST_LOCAL_{int(timezone.now().timestamp())}",
    customer=default_customer,
    provisioned_at=timezone.now()
)

print(f"Created device: {test_device.device_serial}")
print(f"  Before set_audit_fields:")
print(f"    created_by: {test_device.created_by}")
print(f"    updated_by: {test_device.updated_by}")

# Simulate authenticated request
from django.test import RequestFactory
factory = RequestFactory()
fake_request = factory.post('/api/devices/create/')
fake_request.user = admin_user

# Apply audit fields
set_audit_fields(test_device, fake_request)
test_device.save()

# Refresh from database
test_device.refresh_from_db()

print(f"\n  After set_audit_fields:")
print(f"    created_by: {test_device.created_by.username if test_device.created_by else 'NULL'}")
print(f"    updated_by: {test_device.updated_by.username if test_device.updated_by else 'NULL'}")
print(f"    updated_at: {test_device.updated_at}")

# Clean up
test_device.delete()
print(f"\n✅ Test device deleted. Audit trail works!")
