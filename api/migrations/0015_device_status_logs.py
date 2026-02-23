# Generated migration for device status tracking, hard reset, and logs

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0014_device_pending_reboot'),
    ]

    operations = [
        migrations.AddField(
            model_name='device',
            name='last_heartbeat',
            field=models.DateTimeField(blank=True, null=True, help_text='Last time device sent a heartbeat'),
        ),
        migrations.AddField(
            model_name='device',
            name='pending_hard_reset',
            field=models.BooleanField(default=False, help_text='Flag to trigger device hard reset on next heartbeat'),
        ),
        migrations.AddField(
            model_name='device',
            name='logs_enabled',
            field=models.BooleanField(default=False, help_text='Enable device to send logs'),
        ),
        migrations.CreateModel(
            name='DeviceLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timestamp', models.DateTimeField(default=django.utils.timezone.now)),
                ('log_level', models.CharField(default='INFO', max_length=16)),
                ('message', models.TextField()),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('device', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='logs', to='api.device')),
            ],
            options={
                'ordering': ['-timestamp'],
            },
        ),
        migrations.AddIndex(
            model_name='devicelog',
            index=models.Index(fields=['device', 'timestamp'], name='api_devicel_device__idx'),
        ),
        migrations.AddIndex(
            model_name='devicelog',
            index=models.Index(fields=['log_level'], name='api_devicel_log_lev_idx'),
        ),
    ]
