"""
Setup script to create a test gateway configuration for ESP32 testing
Run this to populate the database with a sample configuration
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

from api.models import GatewayConfig, SlaveDevice, RegisterMapping
from django.utils import timezone

def create_test_config():
    """Create a complete test configuration"""
    
    # Delete existing configs
    GatewayConfig.objects.all().delete()
    print("Deleted existing configurations")
    
    # Create gateway config
    config = GatewayConfig.objects.create(
        config_id="config-v1-test",
        updated_at=timezone.now(),
        config_schema_ver=1,
        baud_rate=9600,
        data_bits=8,
        stop_bits=1,
        parity=0  # None
    )
    print(f"Created gateway config: {config.config_id}")
    
    # Create first slave device (Solar Inverter)
    slave1 = SlaveDevice.objects.create(
        gateway_config=config,
        slave_id=1,
        device_name="Solar Inverter",
        polling_interval_ms=5000,
        timeout_ms=1000,
        enabled=True
    )
    print(f"Created slave: {slave1.device_name} (ID: {slave1.slave_id})")
    
    # Add registers for slave 1
    registers_slave1 = [
        {
            "label": "voltage",
            "address": 30001,
            "num_registers": 1,
            "function_code": 3,
            "data_type": 0,  # UINT16
            "scale_factor": 0.1,
            "offset": 0.0,
            "enabled": True
        },
        {
            "label": "current",
            "address": 30002,
            "num_registers": 1,
            "function_code": 3,
            "data_type": 0,  # UINT16
            "scale_factor": 0.01,
            "offset": 0.0,
            "enabled": True
        },
        {
            "label": "power",
            "address": 30003,
            "num_registers": 2,
            "function_code": 3,
            "data_type": 2,  # UINT32
            "scale_factor": 1.0,
            "offset": 0.0,
            "enabled": True
        },
        {
            "label": "frequency",
            "address": 30005,
            "num_registers": 1,
            "function_code": 3,
            "data_type": 0,  # UINT16
            "scale_factor": 0.01,
            "offset": 0.0,
            "enabled": True
        },
    ]
    
    for reg_data in registers_slave1:
        RegisterMapping.objects.create(slave=slave1, **reg_data)
    print(f"  Added {len(registers_slave1)} registers to slave 1")
    
    # Create second slave device (Battery Manager)
    slave2 = SlaveDevice.objects.create(
        gateway_config=config,
        slave_id=2,
        device_name="Battery Manager",
        polling_interval_ms=10000,
        timeout_ms=1000,
        enabled=True
    )
    print(f"Created slave: {slave2.device_name} (ID: {slave2.slave_id})")
    
    # Add registers for slave 2
    registers_slave2 = [
        {
            "label": "battery_voltage",
            "address": 40001,
            "num_registers": 1,
            "function_code": 3,
            "data_type": 0,  # UINT16
            "scale_factor": 0.1,
            "offset": 0.0,
            "enabled": True
        },
        {
            "label": "battery_current",
            "address": 40002,
            "num_registers": 1,
            "function_code": 3,
            "data_type": 1,  # INT16 (can be negative for discharge)
            "scale_factor": 0.1,
            "offset": 0.0,
            "enabled": True
        },
        {
            "label": "state_of_charge",
            "address": 40003,
            "num_registers": 1,
            "function_code": 3,
            "data_type": 0,  # UINT16
            "scale_factor": 0.1,
            "offset": 0.0,
            "enabled": True
        },
        {
            "label": "battery_temp",
            "address": 40004,
            "num_registers": 1,
            "function_code": 3,
            "data_type": 1,  # INT16 (temperature can be negative)
            "scale_factor": 0.1,
            "offset": -40.0,  # Temperature offset
            "enabled": True
        },
    ]
    
    for reg_data in registers_slave2:
        RegisterMapping.objects.create(slave=slave2, **reg_data)
    print(f"  Added {len(registers_slave2)} registers to slave 2")
    
    print("\n" + "="*50)
    print("✓ Test configuration created successfully!")
    print(f"  Config ID: {config.config_id}")
    print(f"  Slaves: {config.slaves.count()}")
    print(f"  Total Registers: {sum(s.registers.count() for s in config.slaves.all())}")
    print("="*50)
    
    return config

if __name__ == "__main__":
    create_test_config()
