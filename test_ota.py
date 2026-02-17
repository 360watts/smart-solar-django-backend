#!/usr/bin/env python
import urllib.request
import urllib.error
import json

base_url = "https://smart-solar-django-backend-git-dev0-360watts-projects.vercel.app"

print("\n=== Testing OTA Endpoints ===\n")

# Test 1: Health Check
print("1. OTA Health Check:")
try:
    req = urllib.request.Request(f"{base_url}/api/ota/health/")
    req.add_header('User-Agent', 'OTA-Test')
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
        print(f"   Status: {resp.status}")
        print(f"   Response: {json.dumps(data, indent=2)}")
except urllib.error.HTTPError as e:
    print(f"   Status: {e.code}")
    print(f"   Error: {e.reason}")
    if e.code != 404:
        try:
            error_data = json.loads(e.read().decode())
            print(f"   Details: {json.dumps(error_data, indent=2)}")
        except:
            pass
except Exception as e:
    print(f"   Error: {str(e)}")

# Test 2: Device Check
print("\n2. OTA Device Check (test device):")
try:
    payload = json.dumps({
        "device_id": "test-stm32-device",
        "firmware_version": "0x00010000"
    }).encode('utf-8')
    
    req = urllib.request.Request(
        f"{base_url}/api/ota/devices/test-stm32-device/check",
        data=payload,
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
        print(f"   Status: {resp.status}")
        print(f"   Response: {json.dumps(data, indent=2)}")
except urllib.error.HTTPError as e:
    print(f"   Status: {e.code}")
    print(f"   Error: {e.reason}")
    try:
        error_data = json.loads(e.read().decode())
        print(f"   Details: {json.dumps(error_data, indent=2)}")
    except:
        pass
except Exception as e:
    print(f"   Error: {str(e)}")

# Test 3: Firmware List
print("\n3. Firmware List (requires admin auth):")
try:
    req = urllib.request.Request(f"{base_url}/api/ota/firmware/")
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
        print(f"   Status: {resp.status}")
        print(f"   Response: {json.dumps(data, indent=2)}")
except urllib.error.HTTPError as e:
    print(f"   Status: {e.code}")
    if e.code == 401:
        print("   Expected 401 (authentication required)")
    print(f"   Error: {e.reason}")
except Exception as e:
    print(f"   Error: {str(e)}")

print("\n=== Tests Complete ===\n")
