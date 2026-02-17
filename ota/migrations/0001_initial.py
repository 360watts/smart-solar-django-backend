# Generated migration for OTA app

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('api', '0005_add_alert_model'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='OTAConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('enable_auto_update', models.BooleanField(default=False, help_text='Automatically push updates to devices')),
                ('update_strategy', models.CharField(choices=[('immediate', 'Immediate - Push updates immediately'), ('scheduled', 'Scheduled - Push during maintenance window'), ('manual', 'Manual - Wait for device to request')], default='manual', max_length=32)),
                ('max_concurrent_updates', models.PositiveIntegerField(default=5, help_text='Max devices updating simultaneously')),
                ('firmware_retention_days', models.PositiveIntegerField(default=30, help_text='Keep old firmware files for N days')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name_plural': 'OTA Configuration',
            },
        ),
        migrations.CreateModel(
            name='FirmwareVersion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('version', models.CharField(help_text='e.g., 0x00020000', max_length=32, unique=True)),
                ('filename', models.CharField(max_length=255)),
                ('file', models.FileField(help_text='Firmware binary file', upload_to='firmware/')),
                ('size', models.PositiveIntegerField(help_text='File size in bytes')),
                ('checksum', models.CharField(blank=True, help_text='SHA256 checksum', max_length=64, null=True)),
                ('description', models.TextField(blank=True, null=True)),
                ('release_notes', models.TextField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=False, help_text='Only active versions are offered to devices')),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='firmware_created', to=settings.AUTH_USER_MODEL)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='firmware_updated', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name_plural': 'Firmware Versions',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='DeviceUpdateLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('current_firmware', models.CharField(help_text='Firmware version reported by device', max_length=32)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('checking', 'Checking for Updates'), ('available', 'Update Available'), ('downloading', 'Downloading'), ('completed', 'Completed'), ('failed', 'Failed'), ('skipped', 'Skipped')], default='pending', max_length=32)),
                ('bytes_downloaded', models.PositiveIntegerField(default=0)),
                ('attempt_count', models.PositiveIntegerField(default=0)),
                ('error_message', models.TextField(blank=True, null=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('last_checked_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('device', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='update_logs', to='api.device')),
                ('firmware_version', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='device_logs', to='ota.firmwareversion')),
            ],
            options={
                'ordering': ['-started_at'],
            },
        ),
        migrations.AddIndex(
            model_name='deviceupdatelog',
            index=models.Index(fields=['device', '-last_checked_at'], name='ota_deviceu_device_2a7a8b_idx'),
        ),
        migrations.AddIndex(
            model_name='deviceupdatelog',
            index=models.Index(fields=['status'], name='ota_deviceu_status_8f3c4d_idx'),
        ),
    ]
