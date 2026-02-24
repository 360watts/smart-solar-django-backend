# Generated migration for adding is_rollback field to DeviceTargetedFirmware

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ota', '0003_alter_devicetargetedfirmware_is_active_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='devicetargetedfirmware',
            name='is_rollback',
            field=models.BooleanField(default=False, help_text='Whether this is a rollback operation'),
        ),
    ]
