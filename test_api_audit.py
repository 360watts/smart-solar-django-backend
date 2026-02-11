"""
Complete test: Verify devices_list API returns audit fields correctly
"""
import requests
import json

BASE_URL = "http://localhost:8000/api"

# Login as rajeev01
print("1. Logging in as rajeev01...")
login_response = requests.post(f"{BASE_URL}/auth/login/", json={
    "username": "rajeev01",
    "password": "Rajeev@123"
})

if login_response.status_code != 200:
    print(f"❌ Login failed: {login_response.status_code}")
    print(login_response.text)
    exit(1)

tokens = login_response.json()
access_token = tokens['access']
print("✅ Login successful")

# Get devices list
print("\n2. Fetching devices list...")
headers = {"Authorization": f"Bearer {access_token}"}
devices_response = requests.get(f"{BASE_URL}/devices/?page=1&page_size=3", headers=headers)

if devices_response.status_code != 200:
    print(f"❌ Devices list failed: {devices_response.status_code}")
    print(devices_response.text)
    exit(1)

data = devices_response.json()
print(f"✅ Devices list successful")
print(f"\nTotal devices: {data.get('total_count', 0)}")
print(f"Returned: {len(data.get('devices', []))} devices")

# Check first device for audit fields
if data.get('devices'):
    device = data['devices'][0]
    print(f"\n=== Device: {device['device_serial']} ===")
    print(f"  Created By: {device.get('created_by_username', 'MISSING FIELD')}")
    print(f"  Created At: {device.get('created_at', 'MISSING FIELD')}")
    print(f"  Updated By: {device.get('updated_by_username', 'MISSING FIELD')}")
    print(f"  Updated At: {device.get('updated_at', 'MISSING FIELD')}")
    
    has_all_fields = all([
        'created_by_username' in device,
        'created_at' in device,
        'updated_by_username' in device,
        'updated_at' in device
    ])
    
    if has_all_fields:
        print(f"\n✅ All audit fields present!")
    else:
        print(f"\n❌ Missing audit fields:")
        print(f"Available fields: {list(device.keys())}")
else:
    print("\n❌ No devices returned")
