# Smart Solar IoT Platform - Database Architecture Documentation

## Overview

This document describes the database architecture for the Smart Solar IoT monitoring platform. The system uses Django with SQLite (development) / PostgreSQL (production) as the primary data store.

---

## Entity Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              SMART SOLAR DATABASE SCHEMA                                 │
└─────────────────────────────────────────────────────────────────────────────────────────┘

                    ┌──────────────────┐
                    │   Django User    │
                    │   (auth_user)    │
                    ├──────────────────┤
                    │ id               │
                    │ username         │
                    │ email            │
                    │ password         │
                    │ first_name       │
                    │ last_name        │
                    │ is_staff         │
                    │ is_superuser     │
                    │ date_joined      │
                    └────────┬─────────┘
                             │
                             │ 1:1
                             ▼
                    ┌──────────────────┐
                    │   UserProfile    │
                    │   (Staff Only)   │
                    ├──────────────────┤
                    │ id               │
                    │ user_id (FK)     │
                    │ mobile_number    │
                    │ address          │
                    └──────────────────┘


┌─────────────────────────┐           ┌──────────────────────────┐
│       Customer          │           │        Device            │
│   (Solar Owners)        │           │    (ESP32 Gateways)      │
├─────────────────────────┤           ├──────────────────────────┤
│ id                      │──1:N──────│ id                       │
│ customer_id (unique)    │           │ device_serial (unique)   │
│ first_name              │           │ customer_id (FK)         │
│ last_name               │           │ user_id (FK) [Legacy]    │
│ email (unique)          │           │ public_key_algorithm     │
│ mobile_number           │           │ csr_pem                  │
│ address                 │           │ provisioned_at           │
│ created_at              │           │ config_version           │
│ is_active               │           └────────────┬─────────────┘
│ notes                   │                        │
└─────────────────────────┘                        │ 1:N
                                                   ▼
                                      ┌──────────────────────────┐
                                      │     TelemetryData        │
                                      │   (Time-Series Data)     │
                                      ├──────────────────────────┤
                                      │ id                       │
                                      │ device_id (FK)           │
                                      │ timestamp                │
                                      │ data_type                │
                                      │ value                    │
                                      │ unit                     │
                                      │ slave_id                 │
                                      │ register_label           │
                                      │ quality                  │
                                      └──────────────────────────┘


┌─────────────────────────┐           ┌──────────────────────────┐
│     GatewayConfig       │           │      SlaveDevice         │
│   (Modbus Settings)     │           │   (Modbus Slaves)        │
├─────────────────────────┤           ├──────────────────────────┤
│ id                      │──1:N──────│ id                       │
│ config_id (unique)      │           │ gateway_config_id (FK)   │
│ name                    │           │ slave_id                 │
│ updated_at              │           │ device_name              │
│ config_schema_ver       │           │ polling_interval_ms      │
│ baud_rate               │           │ timeout_ms               │
│ data_bits               │           │ enabled                  │
│ stop_bits               │           └────────────┬─────────────┘
│ parity                  │                        │
└─────────────────────────┘                        │ 1:N
                                                   ▼
                                      ┌──────────────────────────┐
                                      │    RegisterMapping       │
                                      │   (Modbus Registers)     │
                                      ├──────────────────────────┤
                                      │ id                       │
                                      │ slave_id (FK)            │
                                      │ label                    │
                                      │ address                  │
                                      │ num_registers            │
                                      │ function_code            │
                                      │ data_type                │
                                      │ scale_factor             │
                                      │ offset                   │
                                      │ enabled                  │
                                      └──────────────────────────┘
```

---

## Model Descriptions

### 1. User Management

#### Django User (Built-in)
Standard Django authentication model for staff and admin users.

| Field | Type | Description |
|-------|------|-------------|
| id | AutoField | Primary key |
| username | CharField(150) | Unique username |
| email | EmailField | User email |
| password | CharField | Hashed password |
| first_name | CharField(150) | First name |
| last_name | CharField(150) | Last name |
| is_staff | Boolean | Can access admin site |
| is_superuser | Boolean | Full permissions |
| date_joined | DateTime | Account creation date |

#### UserProfile
Extended profile for staff/employee users.

| Field | Type | Description |
|-------|------|-------------|
| id | AutoField | Primary key |
| user | OneToOneField(User) | Link to Django User |
| mobile_number | CharField(15) | Phone number |
| address | TextField | Physical address |

### 2. Customer Management

#### Customer
Solar system owners/customers (separate from staff users).

| Field | Type | Description |
|-------|------|-------------|
| id | AutoField | Primary key |
| customer_id | CharField(64) | Unique business identifier |
| first_name | CharField(100) | Customer first name |
| last_name | CharField(100) | Customer last name |
| email | EmailField | Unique email |
| mobile_number | CharField(15) | Phone number |
| address | TextField | Physical address |
| created_at | DateTime | Account creation |
| is_active | Boolean | Account status |
| notes | TextField | Admin notes |

### 3. Device Management

#### Device
ESP32 gateway devices that collect solar data.

| Field | Type | Description |
|-------|------|-------------|
| id | AutoField | Primary key |
| device_serial | CharField(64) | Unique MAC/Serial |
| customer | ForeignKey(Customer) | Device owner |
| user | ForeignKey(User) | Legacy field (deprecated) |
| public_key_algorithm | CharField(32) | Crypto algorithm |
| csr_pem | TextField | Certificate signing request |
| provisioned_at | DateTime | First connection |
| config_version | CharField(32) | Current config ID |

### 4. Configuration Management

#### GatewayConfig
Modbus gateway configuration presets.

| Field | Type | Description |
|-------|------|-------------|
| id | AutoField | Primary key |
| config_id | CharField(64) | Unique config identifier |
| name | CharField(100) | Human-readable name |
| updated_at | DateTime | Last modification |
| config_schema_ver | PositiveInteger | Schema version |
| baud_rate | PositiveInteger | Serial baud rate (default: 9600) |
| data_bits | PositiveSmallInteger | Data bits (default: 8) |
| stop_bits | PositiveSmallInteger | Stop bits (default: 1) |
| parity | PositiveSmallInteger | Parity mode (0=None, 1=Odd, 2=Even) |

#### SlaveDevice
Modbus slave devices connected to gateway.

| Field | Type | Description |
|-------|------|-------------|
| id | AutoField | Primary key |
| gateway_config | ForeignKey(GatewayConfig) | Parent config |
| slave_id | PositiveSmallInteger | Modbus address (1-247) |
| device_name | CharField(64) | Device label |
| polling_interval_ms | PositiveInteger | Poll frequency |
| timeout_ms | PositiveInteger | Response timeout |
| enabled | Boolean | Active status |

**Constraints:**
- Unique together: (gateway_config, slave_id)

#### RegisterMapping
Modbus register definitions for data extraction.

| Field | Type | Description |
|-------|------|-------------|
| id | AutoField | Primary key |
| slave | ForeignKey(SlaveDevice) | Parent slave |
| label | CharField(64) | Register name (e.g., "voltage") |
| address | PositiveInteger | Modbus register address |
| num_registers | PositiveSmallInteger | Number of registers |
| function_code | PositiveSmallInteger | Modbus function (3=Read Holding) |
| data_type | PositiveSmallInteger | Data format enum |
| scale_factor | Float | Multiplication factor |
| offset | Float | Addition offset |
| enabled | Boolean | Active status |

### 5. Telemetry Data

#### TelemetryData
Time-series data from devices.

| Field | Type | Description |
|-------|------|-------------|
| id | AutoField | Primary key |
| device | ForeignKey(Device) | Source device |
| timestamp | DateTime | Measurement time |
| data_type | CharField(64) | Metric name (voltage, current, etc.) |
| value | Float | Numeric value |
| unit | CharField(16) | Unit of measurement |
| slave_id | PositiveSmallInteger | Modbus slave source |
| register_label | CharField(64) | Register label |
| quality | CharField(16) | Data quality flag |

**Indexes:**
- Composite: (device, timestamp)
- Single: (data_type)

---

## Current Issues & Technical Debt

### 1. **Legacy User Field in Device Model**
```python
user = models.ForeignKey(User, related_name="legacy_devices", on_delete=models.SET_NULL, null=True, blank=True)
```
- **Issue:** Devices have both `customer` and `user` foreign keys
- **Impact:** Confusing data model, potential inconsistencies
- **Recommendation:** Remove after full migration to Customer model

### 2. **No Alert Persistence**
- **Issue:** Alerts are generated dynamically in views, not stored
- **Impact:** No alert history, acknowledgment, or audit trail
- **Recommendation:** Create Alert model

### 3. **SQLite in Production Risk**
- **Issue:** Using SQLite for time-series IoT data
- **Impact:** Poor performance at scale, no concurrent writes
- **Recommendation:** Use PostgreSQL with TimescaleDB extension

### 4. **No Data Partitioning**
- **Issue:** TelemetryData table will grow unbounded
- **Impact:** Query performance degradation over time
- **Recommendation:** Implement time-based partitioning

### 5. **Missing Audit Trail**
- **Issue:** No tracking of who changed what and when
- **Impact:** Compliance and debugging difficulties
- **Recommendation:** Add django-simple-history or similar

---

## Data Flow

```
┌──────────────────┐
│   ESP32 Device   │
│  (Solar Gateway) │
└────────┬─────────┘
         │
         │ 1. POST /api/devices/provision
         │    {"hwId": "MAC", "model": "esp32"}
         ▼
┌──────────────────┐
│  Provision API   │ ─────► Device table (created/updated)
└────────┬─────────┘
         │
         │ 2. POST /api/devices/{id}/config
         │    {"deviceId": "...", "firmwareVersion": "..."}
         ▼
┌──────────────────┐
│   Config API     │ ─────► Returns GatewayConfig + Slaves + Registers
└────────┬─────────┘
         │
         │ 3. POST /api/telemetry/ingest
         │    {"deviceId": "...", "dataType": "voltage", "value": 240.5}
         ▼
┌──────────────────┐
│  Telemetry API   │ ─────► TelemetryData table (INSERT)
└────────┬─────────┘
         │
         │ 4. POST /api/devices/{id}/heartbeat
         │    {"deviceId": "...", "uptimeSeconds": 3600}
         ▼
┌──────────────────┐
│  Heartbeat API   │ ─────► Returns commands (updateConfig, reboot, etc.)
└──────────────────┘
```

---

## API Endpoints Summary

### Device Endpoints (ESP32)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/devices/provision` | Register new device |
| POST | `/api/devices/{id}/config` | Get device configuration |
| POST | `/api/devices/{id}/heartbeat` | Send heartbeat, get commands |
| POST | `/api/devices/{id}/logs` | Upload device logs |
| POST | `/api/telemetry/ingest` | Send telemetry data |

### Management Endpoints (React Frontend)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/devices/` | List all devices |
| POST | `/api/devices/create/` | Register device |
| PUT | `/api/devices/{id}/` | Update device |
| DELETE | `/api/devices/{id}/delete/` | Delete device |
| GET | `/api/telemetry/` | Get telemetry data |
| GET | `/api/alerts/` | Get system alerts |
| GET | `/api/health/` | Get system health |
| GET | `/api/kpis/` | Get KPI metrics |

### User Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register/` | Register user |
| POST | `/api/auth/login/` | Login |
| POST | `/api/auth/logout/` | Logout |
| GET | `/api/users/` | List users |
| POST | `/api/users/create/` | Create user |
| PUT | `/api/users/{id}/` | Update user |
| DELETE | `/api/users/{id}/delete/` | Delete user |

---

## Security Considerations

### Current Implementation
1. **JWT Authentication** - Using djangorestframework-simplejwt
2. **Password Hashing** - Django's PBKDF2 with SHA256
3. **CORS Enabled** - For React frontend communication

### Security Gaps
1. **Hardcoded JWT Secret** - Line in views.py: `jwt_secret = "your-jwt-secret-key"`
2. **No Rate Limiting** - API endpoints vulnerable to abuse
3. **No Input Sanitization** - SQL injection risks in search queries
4. **Device Authentication** - Minimal validation on telemetry ingest

---

## Database Statistics (Current)

To get current database statistics, run:

```bash
python manage.py shell
```

```python
from api.models import *
from django.contrib.auth.models import User

print(f"Users: {User.objects.count()}")
print(f"Customers: {Customer.objects.count()}")
print(f"Devices: {Device.objects.count()}")
print(f"Gateway Configs: {GatewayConfig.objects.count()}")
print(f"Slave Devices: {SlaveDevice.objects.count()}")
print(f"Register Mappings: {RegisterMapping.objects.count()}")
print(f"Telemetry Records: {TelemetryData.objects.count()}")
```

---

## Recommendations for Scale

### Short-term (< 100 devices)
- Current SQLite setup is acceptable for development
- Add database indexes for frequently queried fields
- Implement connection pooling

### Medium-term (100-1000 devices)
- Migrate to PostgreSQL
- Implement data retention policies (delete data older than X months)
- Add read replicas for dashboard queries

### Long-term (1000+ devices)
- Use TimescaleDB for time-series data
- Implement data warehousing for analytics
- Consider message queue (Redis/RabbitMQ) for telemetry ingestion
- Horizontal scaling with database sharding

---

*Document Version: 1.0*
*Last Updated: February 4, 2026*
