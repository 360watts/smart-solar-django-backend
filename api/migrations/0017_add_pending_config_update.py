from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0016_add_cfgver_and_ack'),
    ]

    operations = [
        migrations.AddField(
            model_name='device',
            name='pending_config_update',
            field=models.BooleanField(
                default=False,
                help_text='Set when preset/slave changes so device fetches config on next heartbeat',
            ),
        ),
    ]
