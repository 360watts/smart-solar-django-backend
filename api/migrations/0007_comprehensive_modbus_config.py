# Generated manually - Comprehensive Modbus Configuration Extension
# Created on: 2026-02-11

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0006_add_audit_fields'),
    ]

    operations = [
        # Extend GatewayConfig model
        migrations.RemoveField(
            model_name='gatewayconfig',
            name='parity',
        ),
        migrations.AddField(
            model_name='gatewayconfig',
            name='protocol_type',
            field=models.CharField(choices=[('RTU', 'Modbus RTU'), ('ASCII', 'Modbus ASCII'), ('TCP', 'Modbus TCP')], default='RTU', max_length=10),
        ),
        migrations.AddField(
            model_name='gatewayconfig',
            name='parity',
            field=models.CharField(choices=[('N', 'None'), ('E', 'Even'), ('O', 'Odd')], default='N', max_length=1),
        ),
        migrations.AddField(
            model_name='gatewayconfig',
            name='interface_type',
            field=models.CharField(choices=[('RS485', 'RS-485'), ('RS232', 'RS-232'), ('ETH', 'Ethernet')], default='RS485', max_length=10),
        ),
        migrations.AddField(
            model_name='gatewayconfig',
            name='global_response_timeout_ms',
            field=models.PositiveIntegerField(default=1000, help_text='Default response timeout in ms'),
        ),
        migrations.AddField(
            model_name='gatewayconfig',
            name='inter_frame_delay_ms',
            field=models.PositiveIntegerField(default=50, help_text='Gap between frames in ms'),
        ),
        migrations.AddField(
            model_name='gatewayconfig',
            name='global_retry_count',
            field=models.PositiveSmallIntegerField(default=3, help_text='Default retry attempts'),
        ),
        migrations.AddField(
            model_name='gatewayconfig',
            name='global_retry_delay_ms',
            field=models.PositiveIntegerField(default=100, help_text='Wait between retries in ms'),
        ),
        migrations.AddField(
            model_name='gatewayconfig',
            name='global_poll_interval_ms',
            field=models.PositiveIntegerField(default=5000, help_text='Default polling interval in ms'),
        ),
        
        # Create DevicePreset model
        migrations.CreateModel(
            name='DevicePreset',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('manufacturer', models.CharField(blank=True, max_length=100)),
                ('model', models.CharField(blank=True, max_length=100)),
                ('device_type', models.CharField(choices=[('SOLAR_INV', 'Solar Inverter'), ('ENERGY_MTR', 'Energy Meter'), ('PLC', 'PLC Controller'), ('TEMP_SENSOR', 'Temperature Sensor'), ('VFD', 'Variable Frequency Drive'), ('CUSTOM', 'Custom Device')], max_length=20)),
                ('description', models.TextField(blank=True)),
                ('version', models.CharField(default='1.0', max_length=20)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('is_active', models.BooleanField(default=True)),
                ('default_baud_rate', models.PositiveIntegerField(default=9600)),
                ('default_parity', models.CharField(choices=[('N', 'None'), ('E', 'Even'), ('O', 'Odd')], default='N', max_length=1)),
                ('default_data_bits', models.PositiveSmallIntegerField(default=8)),
                ('default_stop_bits', models.PositiveSmallIntegerField(default=1)),
                ('default_timeout_ms', models.PositiveIntegerField(default=1000)),
                ('default_poll_interval_ms', models.PositiveIntegerField(default=5000)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='auth.user')),
            ],
            options={
                'ordering': ['manufacturer', 'model'],
            },
        ),
        
        # Extend SlaveDevice model
        migrations.RemoveField(
            model_name='slavedevice',
            name='timeout_ms',
        ),
        migrations.AddField(
            model_name='slavedevice',
            name='device_type',
            field=models.CharField(blank=True, help_text='Device model for preset mappings', max_length=64),
        ),
        migrations.AddField(
            model_name='slavedevice',
            name='response_timeout_ms',
            field=models.PositiveIntegerField(default=1000),
        ),
        migrations.AddField(
            model_name='slavedevice',
            name='retry_count',
            field=models.PositiveSmallIntegerField(default=3),
        ),
        migrations.AddField(
            model_name='slavedevice',
            name='retry_delay_ms',
            field=models.PositiveIntegerField(default=100),
        ),
        migrations.AddField(
            model_name='slavedevice',
            name='priority',
            field=models.CharField(choices=[('HIGH', 'High Priority'), ('NORMAL', 'Normal Priority'), ('LOW', 'Low Priority')], default='NORMAL', max_length=10),
        ),
        migrations.AddField(
            model_name='slavedevice',
            name='description',
            field=models.TextField(blank=True, help_text='Device description or notes'),
        ),
        migrations.AddField(
            model_name='slavedevice',
            name='preset',
            field=models.ForeignKey(blank=True, help_text='Device preset template', null=True, on_delete=django.db.models.deletion.SET_NULL, to='api.devicepreset'),
        ),
        migrations.AlterField(
            model_name='slavedevice',
            name='slave_id',
            field=models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(247)]),
        ),
        
        # Completely recreate RegisterMapping model with new comprehensive fields
        migrations.DeleteModel(
            name='RegisterMapping',
        ),
        migrations.CreateModel(
            name='RegisterMapping',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Human-readable register name', max_length=64)),
                ('address', models.PositiveIntegerField(validators=[django.core.validators.MaxValueValidator(65535)])),
                ('register_type', models.CharField(choices=[('COIL', 'Coil (0x)'), ('DISCRETE', 'Discrete Input (1x)'), ('INPUT', 'Input Register (3x)'), ('HOLDING', 'Holding Register (4x)')], default='HOLDING', max_length=10)),
                ('function_code', models.PositiveSmallIntegerField(choices=[(1, 'Read Coils (0x01)'), (2, 'Read Discrete Inputs (0x02)'), (3, 'Read Holding Registers (0x03)'), (4, 'Read Input Registers (0x04)'), (5, 'Write Single Coil (0x05)'), (6, 'Write Single Register (0x06)'), (15, 'Write Multiple Coils (0x0F)'), (16, 'Write Multiple Registers (0x10)')], default=3)),
                ('register_count', models.PositiveSmallIntegerField(default=1, validators=[django.core.validators.MaxValueValidator(125)])),
                ('enabled', models.BooleanField(default=True)),
                ('data_type', models.CharField(choices=[('INT16', '16-bit Signed Integer'), ('UINT16', '16-bit Unsigned Integer'), ('INT32', '32-bit Signed Integer'), ('UINT32', '32-bit Unsigned Integer'), ('FLOAT32', '32-bit Float'), ('FLOAT64', '64-bit Float'), ('STRING', 'ASCII String'), ('BOOL', 'Boolean')], default='UINT16', max_length=10)),
                ('byte_order', models.CharField(choices=[('BE', 'Big Endian (AB)'), ('LE', 'Little Endian (BA)')], default='BE', max_length=10)),
                ('word_order', models.CharField(blank=True, choices=[('BE', 'Big Endian (AB CD)'), ('LE', 'Little Endian (CD AB)'), ('MBE', 'Mid-Big Endian (BA DC)'), ('MLE', 'Mid-Little Endian (DC BA)')], default='BE', max_length=10)),
                ('bit_position', models.PositiveSmallIntegerField(blank=True, help_text='For single bit extraction (0-15)', null=True, validators=[django.core.validators.MaxValueValidator(15)])),
                ('scale_factor', models.FloatField(default=1.0, help_text='Multiply raw value by this')),
                ('offset', models.FloatField(default=0.0, help_text='Add this to scaled value')),
                ('formula', models.CharField(blank=True, help_text='Custom formula using x as variable', max_length=200)),
                ('decimal_places', models.PositiveSmallIntegerField(default=2, validators=[django.core.validators.MaxValueValidator(6)])),
                ('unit', models.CharField(blank=True, help_text='Engineering unit (V, A, W, etc.)', max_length=20)),
                ('category', models.CharField(blank=True, help_text='Logical grouping', max_length=50)),
                ('min_value', models.FloatField(blank=True, help_text='Valid range minimum', null=True)),
                ('max_value', models.FloatField(blank=True, help_text='Valid range maximum', null=True)),
                ('dead_band', models.FloatField(blank=True, help_text='Minimum change to report', null=True)),
                ('access_mode', models.CharField(choices=[('R', 'Read Only'), ('RW', 'Read/Write'), ('W', 'Write Only')], default='R', max_length=5)),
                ('high_alarm_threshold', models.FloatField(blank=True, null=True)),
                ('low_alarm_threshold', models.FloatField(blank=True, null=True)),
                ('value_mapping', models.JSONField(blank=True, default=dict, help_text='Map values to descriptions {"0": "Off", "1": "On"}')),
                ('string_length', models.PositiveSmallIntegerField(blank=True, help_text='For ASCII string registers', null=True)),
                ('is_signed', models.BooleanField(default=True, help_text='For INT16 vs UINT16 interpretation')),
                ('description', models.TextField(blank=True, help_text='Register description')),
                ('slave', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='registers', to='api.slavedevice')),
            ],
            options={
                'ordering': ['address'],
            },
        ),
        
        # Create PresetRegister model
        migrations.CreateModel(
            name='PresetRegister',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=64)),
                ('address', models.PositiveIntegerField()),
                ('register_type', models.CharField(choices=[('COIL', 'Coil (0x)'), ('DISCRETE', 'Discrete Input (1x)'), ('INPUT', 'Input Register (3x)'), ('HOLDING', 'Holding Register (4x)')], max_length=10)),
                ('function_code', models.PositiveSmallIntegerField(choices=[(1, 'Read Coils (0x01)'), (2, 'Read Discrete Inputs (0x02)'), (3, 'Read Holding Registers (0x03)'), (4, 'Read Input Registers (0x04)'), (5, 'Write Single Coil (0x05)'), (6, 'Write Single Register (0x06)'), (15, 'Write Multiple Coils (0x0F)'), (16, 'Write Multiple Registers (0x10)')], default=3)),
                ('register_count', models.PositiveSmallIntegerField(default=1)),
                ('data_type', models.CharField(choices=[('INT16', '16-bit Signed Integer'), ('UINT16', '16-bit Unsigned Integer'), ('INT32', '32-bit Signed Integer'), ('UINT32', '32-bit Unsigned Integer'), ('FLOAT32', '32-bit Float'), ('FLOAT64', '64-bit Float'), ('STRING', 'ASCII String'), ('BOOL', 'Boolean')], default='UINT16', max_length=10)),
                ('byte_order', models.CharField(choices=[('BE', 'Big Endian (AB)'), ('LE', 'Little Endian (BA)')], default='BE', max_length=10)),
                ('word_order', models.CharField(blank=True, choices=[('BE', 'Big Endian (AB CD)'), ('LE', 'Little Endian (CD AB)'), ('MBE', 'Mid-Big Endian (BA DC)'), ('MLE', 'Mid-Little Endian (DC BA)')], default='BE', max_length=10)),
                ('scale_factor', models.FloatField(default=1.0)),
                ('offset', models.FloatField(default=0.0)),
                ('unit', models.CharField(blank=True, max_length=20)),
                ('category', models.CharField(blank=True, max_length=50)),
                ('decimal_places', models.PositiveSmallIntegerField(default=2)),
                ('min_value', models.FloatField(blank=True, null=True)),
                ('max_value', models.FloatField(blank=True, null=True)),
                ('description', models.TextField(blank=True)),
                ('value_mapping', models.JSONField(blank=True, default=dict)),
                ('is_required', models.BooleanField(default=True, help_text='Essential register for this device type')),
                ('display_order', models.PositiveSmallIntegerField(default=100)),
                ('preset', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='registers', to='api.devicepreset')),
            ],
            options={
                'ordering': ['display_order', 'category', 'name'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='presetregister',
            unique_together={('preset', 'address')},
        ),
        
        # Add preset_register field to RegisterMapping
        migrations.AddField(
            model_name='registermapping',
            name='preset_register',
            field=models.ForeignKey(blank=True, help_text='Linked preset register', null=True, on_delete=django.db.models.deletion.SET_NULL, to='api.presetregister'),
        ),
        
        # Add indexes
        migrations.AddIndex(
            model_name='registermapping',
            index=models.Index(fields=['slave', 'address'], name='api_registermapping_slave_addr_idx'),
        ),
        migrations.AddIndex(
            model_name='registermapping',
            index=models.Index(fields=['enabled'], name='api_registermapping_enabled_idx'),
        ),
    ]
