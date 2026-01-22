# ESP32-Django API Fix Summary

## Changes Made

### 1. Fixed Provision Endpoint (CRITICAL FIX)

**Problem**: ESP32 was sending `400 Bad Request` because payload format mismatch

**ESP32 sends**:
```json
{
  "hwId": "E4:65:B8:53:F8:C4",
  "model": "esp32 wroom", 
  "claimNonce": "IM_YOUR_DEVICE"
}
```

**Django now expects** (serializers.py):
```python
class ProvisionSerializer(serializers.Serializer):
    hwId = serializers.CharField()
    model = serializers.CharField(required=False, allow_blank=True)
    claimNonce = serializers.CharField(required=False, allow_blank=True)
```

**Django now returns** (views.py):
```json
{
  "status": "success",
  "deviceId": "E4:65:B8:53:F8:C4",
  "provisionedAt": "2025-11-18T...",
  "credentials": {
    "type": "api-key",
    "secret": "secret-E4:65:B8:53:F8:C4"
  }
}
```

### 2. Fixed URL Paths

**Old URLs** (wrong):
- `/api/provision/`
- `/api/config/gateway`
- `/api/heartbeat/`

**New URLs** (matching ESP32):
- `/api/devices/provision`
- `/api/devices/{device_id}/config`
- `/api/devices/{device_id}/heartbeat`
- `/api/devices/{device_id}/logs`

### 3. Fixed Heartbeat Response

**ESP32 expects**:
```json
{
  "status": 1,  // Important: ESP32 checks for status == 1
  "serverTime": "2025-11-18T...",
  "commands": {
    "updateConfig": 0,  // Set to 1 to trigger config update
    "reboot": 0,
    "updateFirmware": 0,
    "updateNetwork": 0,
    "sendLogs": 0,
    "clearLogs": 0
  },
  "message": "OK"
}
```

### 4. Gateway Config Response Format

Django serializer already matches ESP32 expectation:
```json
{
  "configId": "config-v1-test",
  "updatedAt": "2025-11-18T...",
  "configSchemaVer": 1,
  "uartConfig": {
    "baudRate": 9600,
    "dataBits": 8,
    "stopBits": 1,
    "parity": 0
  },
  "slaves": [
    {
      "slaveId": 1,
      "deviceName": "Solar Inverter",
      "pollingIntervalMs": 5000,
      "timeoutMs": 1000,
      "enabled": true,
      "registers": [...]
    }
  ]
}
```

## How to Test

### 1. Run Database Migrations
```powershell
cd c:\projects\360watts\django\smart-solar-django-backend
python manage.py makemigrations
python manage.py migrate
```

### 2. Create Test Configuration
```powershell
python setup_test_config.py
```

This creates:
- 1 gateway config with ID: `config-v1-test`
- 2 slave devices (Solar Inverter, Battery Manager)
- 8 total registers across both slaves

### 3. Start Django Server
```powershell
python manage.py runserver 192.168.137.1:8000
```

### 4. Flash ESP32
The ESP32 should now:
1. ✓ Connect to WiFi (192.168.137.1)
2. ✓ Successfully provision (GET deviceId)
3. ✓ Fetch gateway configuration
4. ✓ Start Modbus polling
5. ✓ Send heartbeats every interval

## ESP32 Expected Flow

```
STATE_BOOT
  → Connect WiFi
  → STATE_CHECK_PROVISION
  
STATE_CHECK_PROVISION
  → POST /api/devices/provision
  → Receive deviceId + credentials
  → STATE_CHECK_CONFIG
  
STATE_CHECK_CONFIG
  → POST /api/devices/{deviceId}/config
  → Receive full gateway config
  → STATE_RUN_ONLINE
  
STATE_RUN_ONLINE (continuous)
  → Initialize MQTT
  → Start Modbus polling
  → Heartbeat task runs every 60s
    → POST /api/devices/{deviceId}/heartbeat
    → Check for config updates
```

## Troubleshooting

### If ESP32 still gets 400 error:
1. Check Django logs for validation errors
2. Verify ESP32 sends exactly: `{"hwId":"...","model":"...","claimNonce":"..."}`
3. Check URL is: `http://192.168.137.1:8000/api/devices/provision`

### If config fetch fails:
1. Verify device was provisioned (check Django admin or database)
2. Run `setup_test_config.py` to create test config
3. Check URL format: `/api/devices/{deviceId}/config` not `/api/config/gateway`

### If heartbeat gets error:
1. Check ESP32 sends `configId` field in heartbeat payload
2. Verify Django returns `"status": 1` (not `"status": "success"`)
3. Check `commands` object has integer values (0 or 1)

## Files Modified

1. `api/serializers.py` - Updated ProvisionSerializer
2. `api/views.py` - Rewrote provision, config, heartbeat views
3. `api/urls.py` - Fixed URL patterns
4. `setup_test_config.py` - Created (new file for testing)
