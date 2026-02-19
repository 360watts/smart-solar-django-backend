from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0011_make_gatewayconfig_nullable'),
    ]

    operations = [
        migrations.RenameField(
            model_name='device',
            old_name='owner',
            new_name='user',
        ),
    ]
