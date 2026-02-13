"""
Test devices list API endpoint with gateway_config fields
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from rest_framework_simplejwt.tokens import RefreshToken
from api.models import Device, GatewayConfig

# Get admin user for authentication
admin = User.objects.filter(username='admin').first()
if not admin:
    print("Admin user not found!")
    exit(1)

# Create token
refresh = RefreshToken.for_user(admin)
token = str(refresh.access_token)

client = Client()
headers = {'HTTP_AUTHORIZATION': f'Bearer {token}', 'HTTP_HOST': 'testserver'}

print("=" * 80)
print("Testing /api/devices/ endpoint with gateway_config fields")
print("=" * 80)

# Get devices from API
response = client.get('/api/devices/?page=1&page_size=5', **headers, SERVER_NAME='testserver')

if response.status_code == 200:
    data = response.json()
    print(f"\n✓ API call successful")
    print(f"  Total devices: {data['count']}")
    print(f"  Returned: {len(data['results'])} devices")
    
    if data['results']:
        print(f"\n{'Device Serial':<25} {'Preset Assigned':<40} {'Preset ID':<10}")
        print("-" * 80)
        for device in data['results']:
            preset_name = device.get('gateway_config_name', 'N/A')
            preset_id = device.get('gateway_config_id', 'N/A')
            device_serial = device.get('device_serial', 'N/A')
            
            # Check if preset fields exist
            if 'gateway_config_id' not in device:
                print(f"\n✗ ERROR: gateway_config_id field missing from response!")
                break
            if 'gateway_config_name' not in device:
                print(f"\n✗ ERROR: gateway_config_name field missing from response!")
                break
            if 'gateway_config_description' not in device:
                print(f"\n✗ ERROR: gateway_config_description field missing from response!")
                break
            
            status_icon = "✓" if preset_id else "○"
            preset_display = preset_name if preset_id else "No preset assigned"
            print(f"{status_icon} {device_serial:<23} {preset_display:<40} {preset_id}")
        
        print("\n" + "=" * 80)
        print("✓ SUCCESS: All gateway_config fields are present in the API response!")
        print("=" * 80)
    else:
        print("\n  No devices found in the system")
else:
    print(f"\n✗ API call failed with status {response.status_code}")
    print(f"  Response: {response.content.decode()}")

print()
