# Generated migration for adding config sync timestamps

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0017_add_pending_config_update'),
    ]

    operations = [
        migrations.AddField(
            model_name='device',
            name='config_downloaded_at',
            field=models.DateTimeField(blank=True, help_text='Last time device downloaded config from /config endpoint', null=True),
        ),
        migrations.AddField(
            model_name='device',
            name='config_acked_at',
            field=models.DateTimeField(blank=True, help_text='Last time device acknowledged config via /configAck endpoint', null=True),
        ),
    ]
