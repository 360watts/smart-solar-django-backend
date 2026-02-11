# Generated migration for audit trail fields

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('api', '0005_add_alert_model'),
    ]

    operations = [
        # Customer: Add created_by, updated_at, updated_by
        migrations.AddField(
            model_name='customer',
            name='created_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='customers_created', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='customer',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddField(
            model_name='customer',
            name='updated_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='customers_updated', to=settings.AUTH_USER_MODEL),
        ),
        # Device: Add created_by, updated_by, updated_at
        migrations.AddField(
            model_name='device',
            name='created_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='devices_created', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='device',
            name='updated_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='devices_updated', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='device',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
        # GatewayConfig: Add created_at, created_by, updated_by
        # Note: updated_at already exists, so we only add the new fields
        migrations.AddField(
            model_name='gatewayconfig',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AddField(
            model_name='gatewayconfig',
            name='created_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='gateway_configs_created', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='gatewayconfig',
            name='updated_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='gateway_configs_updated', to=settings.AUTH_USER_MODEL),
        ),
        # Alert: Add created_by
        migrations.AddField(
            model_name='alert',
            name='created_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='alerts_created', to=settings.AUTH_USER_MODEL),
        ),
    ]
