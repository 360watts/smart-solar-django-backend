import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

from django.db import connection
from django.db.models import Index

# Show current indexes
print("=" * 60)
print("ADDING PERFORMANCE INDEXES TO DATABASE")
print("=" * 60)

with connection.cursor() as cursor:
    # Check existing indexes
    cursor.execute("""
        SELECT indexname FROM pg_indexes 
        WHERE schemaname = 'public'
    """)
    existing_indexes = [row[0] for row in cursor.fetchall()]
    print("\nExisting indexes:")
    for idx in existing_indexes:
        print(f"  - {idx}")

print("\nTo apply indexes, run:")
print("  python manage.py makemigrations")
print("  python manage.py migrate")

print("\nOr create migration manually:")
print("""
# In api/migrations/0006_add_performance_indexes.py

from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('api', '0005_add_alert_model'),
    ]
    
    operations = [
        migrations.AddIndex(
            model_name='device',
            index=models.Index(fields=['customer'], name='device_customer_idx'),
        ),
        migrations.AddIndex(
            model_name='device',
            index=models.Index(fields=['user'], name='device_user_idx'),
        ),
        migrations.AddIndex(
            model_name='device',
            index=models.Index(fields=['provisioned_at'], name='device_prov_date_idx'),
        ),
        migrations.AddIndex(
            model_name='device',
            index=models.Index(fields=['customer', 'provisioned_at'], name='device_cust_date_idx'),
        ),
    ]
""")
