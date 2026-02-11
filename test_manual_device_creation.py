"""
Test script to manually create a device through the web API
to verify audit fields work with authenticated staff users
"""
import requests
import json

# Your production URL
BASE_URL = "https://smart-solar-django-backend.vercel.app/api"

# Login as admin
login_response = requests.post(f"{BASE_URL}/auth/login/", json={
    "username": "admin",
    "password": "your_admin_password_here"  # UPDATE THIS
})

if login_response.status_code == 200:
    tokens = login_response.json()
    access_token = tokens['access']
    
    # Create a test device
    headers = {"Authorization": f"Bearer {access_token}"}
    device_data = {
        "device_serial": "TEST_MANUAL_DEVICE_" + str(int(time.time())),
    }
    
    create_response = requests.post(
        f"{BASE_URL}/devices/create/",
        headers=headers,
        json=device_data
    )
    
    print(f"Status: {create_response.status_code}")
    print(f"Response: {json.dumps(create_response.json(), indent=2)}")
else:
    print(f"Login failed: {login_response.status_code}")
    print(login_response.text)
