"""
Test manual device creation to verify audit trail works correctly
Simulates what happens when Rajeev creates a device through the UI
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

from django.test import RequestFactory
from api.views import create_device
from api.models import User, Device
from rest_framework.test import force_authenticate
import json

# Get rajeev01 user
rajeev = User.objects.get(username="rajeev01")

# Create a mock request (simulating UI creation)
factory = RequestFactory()
request = factory.post('/api/devices/create/', 
    json.dumps({"device_serial": "UI_TEST_RAJEEV"}),
    content_type='application/json'
)
force_authenticate(request, user=rajeev)

# Call the view
response = create_device(request)

print(f"Response Status: {response.status_code}")
print(f"Response Data: {response.data}\n")

# Check the created device
if response.status_code == 201:
    device = Device.objects.get(device_serial="UI_TEST_RAJEEV")
    print(f"✅ Device created successfully!")
    print(f"   Device Serial: {device.device_serial}")
    print(f"   Customer: {device.customer.customer_id}")
    print(f"   Created By: {device.created_by.username if device.created_by else 'NULL'}")
    print(f"   Updated By: {device.updated_by.username if device.updated_by else 'NULL'}")
    print(f"\n   Expected: created_by = rajeev01")
    print(f"   Actual: created_by = {device.created_by.username if device.created_by else 'NULL'}")
    
    # Clean up
    device.delete()
    print(f"\n✅ Test device deleted")
else:
    print(f"❌ Failed to create device: {response.data}")
