# Generated migration for pending_reboot field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0013_add_hw_id_model_to_device'),
    ]

    operations = [
        migrations.AddField(
            model_name='device',
            name='pending_reboot',
            field=models.BooleanField(default=False, help_text='Flag to trigger device reboot on next heartbeat'),
        ),
    ]
