from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0010_slave_priority_register_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='slavedevice',
            name='gateway_config',
            field=models.ForeignKey(
                related_name='slaves',
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                to='api.gatewayconfig',
            ),
        ),
    ]
