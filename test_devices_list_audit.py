"""
Test that the devices_list endpoint returns audit fields
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

from django.test import RequestFactory
from api.views import devices_list
from api.models import User
from rest_framework.test import force_authenticate
import json

# Get rajeev01 user
rajeev = User.objects.get(username="rajeev01")

# Create a mock request
factory = RequestFactory()
request = factory.get('/api/devices/?page=1&page_size=5')
force_authenticate(request, user=rajeev)

# Call the view
response = devices_list(request)

print(f"Response Status: {response.status_code}")
print(f"\nTotal devices returned: {len(response.data.get('devices', []))}")

# Check first device
if response.data.get('devices'):
    first_device = response.data['devices'][0]
    print(f"\n=== First Device ===")
    print(f"Serial: {first_device.get('device_serial')}")
    print(f"Created By: {first_device.get('created_by_username', 'MISSING')}")
    print(f"Updated By: {first_device.get('updated_by_username', 'MISSING')}")
    print(f"Updated At: {first_device.get('updated_at', 'MISSING')}")
    
    # Check if audit fields are present
    has_audit = all([
        'created_by_username' in first_device,
        'created_at' in first_device,
        'updated_by_username' in first_device,
        'updated_at' in first_device
    ])
    
    if has_audit:
        print(f"\n✅ All audit fields present in response!")
    else:
        print(f"\n❌ Some audit fields missing!")
        print(f"Keys in response: {list(first_device.keys())}")
else:
    print("No devices in response")
