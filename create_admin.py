"""
Create admin user for Smart Solar system
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

from django.contrib.auth.models import User

print("=" * 60)
print("CREATING ADMIN USER")
print("=" * 60)
print()

# Create admin user
if not User.objects.filter(username='admin').exists():
    admin = User.objects.create_superuser(
        username='admin',
        email='admin@example.com',
        password='AdminPass123'
    )
    print("✅ Admin user created successfully!")
    print()
    print("LOGIN CREDENTIALS:")
    print("-" * 60)
    print(f"  Username: admin")
    print(f"  Password: AdminPass123")
    print(f"  Email: admin@example.com")
    print()
    print("PROPERTIES:")
    print("-" * 60)
    print(f"  is_staff: {admin.is_staff}")
    print(f"  is_superuser: {admin.is_superuser}")
    print()
else:
    admin = User.objects.get(username='admin')
    print("⚠️  Admin user 'admin' already exists")
    print()
    print("CURRENT ADMIN:")
    print("-" * 60)
    print(f"  Username: {admin.username}")
    print(f"  Email: {admin.email}")
    print(f"  is_staff: {admin.is_staff}")
    print(f"  is_superuser: {admin.is_superuser}")
    print()
    print("To login, use:")
    print(f"  Username: {admin.username}")
    print()

# Show customer count
from api.models import Customer
customer_count = Customer.objects.count()
print()
print("DATABASE STATUS:")
print("-" * 60)
print(f"  Total Customers: {customer_count}")
print(f"  Staff Users: {User.objects.filter(is_staff=True).count()}")
print()
print("=" * 60)
