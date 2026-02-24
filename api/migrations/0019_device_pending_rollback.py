# Generated migration for adding pending_rollback field to Device

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0018_add_config_timestamps'),
    ]

    operations = [
        migrations.AddField(
            model_name='device',
            name='pending_rollback',
            field=models.BooleanField(default=False, help_text='Flag to trigger firmware rollback on next heartbeat'),
        ),
    ]
