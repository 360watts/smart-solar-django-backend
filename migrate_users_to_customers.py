"""
Migration script to separate Users (employees) from Customers (device owners)

This script will:
1. Create Customer records from existing non-staff User records
2. Update Device records to point to new Customer records
3. Optionally remove old non-staff User records

Run this after applying Django migrations:
    python manage.py makemigrations
    python manage.py migrate
    python migrate_users_to_customers.py
"""

import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

from django.contrib.auth.models import User
from api.models import Customer, Device
from django.db import transaction


def migrate_users_to_customers():
    """
    Migrate non-staff users to Customer model
    """
    print("=" * 60)
    print("MIGRATING USERS TO CUSTOMERS")
    print("=" * 60)
    
    # Get all non-staff users (these are actual customers, not employees)
    customer_users = User.objects.filter(is_staff=False)
    print(f"\nFound {customer_users.count()} non-staff users to migrate")
    
    if customer_users.count() == 0:
        print("No non-staff users found. Migration complete!")
        return
    
    migrated_count = 0
    device_update_count = 0
    
    with transaction.atomic():
        for user in customer_users:
            # Check if customer already exists
            customer_id = f"CUST{user.id:08d}"
            
            if Customer.objects.filter(customer_id=customer_id).exists():
                print(f"⚠️  Customer {customer_id} already exists, skipping user {user.username}")
                customer = Customer.objects.get(customer_id=customer_id)
            else:
                # Create Customer from User
                profile = getattr(user, 'userprofile', None)
                
                customer = Customer.objects.create(
                    customer_id=customer_id,
                    first_name=user.first_name or "Customer",
                    last_name=user.last_name or str(user.id),
                    email=user.email or f"customer{user.id}@example.com",
                    mobile_number=profile.mobile_number if profile else None,
                    address=profile.address if profile else None,
                    created_at=user.date_joined,
                    is_active=user.is_active,
                    notes=f"Migrated from User: {user.username}"
                )
                
                print(f"✅ Created Customer: {customer.customer_id} ({customer.first_name} {customer.last_name})")
                migrated_count += 1
            
            # Update all devices belonging to this user
            devices = Device.objects.filter(user=user)
            for device in devices:
                device.customer = customer
                device.save()
                device_update_count += 1
                print(f"   └─ Updated device: {device.device_serial} → Customer {customer.customer_id}")
    
    print("\n" + "=" * 60)
    print("MIGRATION SUMMARY")
    print("=" * 60)
    print(f"✅ Customers created: {migrated_count}")
    print(f"✅ Devices updated: {device_update_count}")
    print(f"📊 Total customers in database: {Customer.objects.count()}")
    print(f"📊 Staff users (employees): {User.objects.filter(is_staff=True).count()}")
    print(f"📊 Non-staff users (to be removed): {User.objects.filter(is_staff=False).count()}")
    
    # Ask if user wants to delete old non-staff users
    print("\n" + "=" * 60)
    print("CLEANUP OPTIONS")
    print("=" * 60)
    print("Non-staff User records are no longer needed.")
    print("They can be safely deleted after verification.")
    print("\nTo delete them, run:")
    print("    python manage.py shell")
    print("    >>> from django.contrib.auth.models import User")
    print("    >>> User.objects.filter(is_staff=False).delete()")
    print("\n⚠️  Make sure to backup your database before deleting!")


if __name__ == "__main__":
    migrate_users_to_customers()
