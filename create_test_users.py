"""
Create test users with different roles
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

from api.models import UserProfile
from django.contrib.auth.models import User

print("=" * 60)
print("CREATING TEST USERS")
print("=" * 60)

# Create a regular USER (device owner)
if not User.objects.filter(username='deviceowner1').exists():
    user1 = User.objects.create_user(
        username='deviceowner1',
        email='owner1@test.com',
        password='test123',
        first_name='John',
        last_name='Doe'
    )
    print(f"✓ Created USER: {user1.username} - {user1.userprofile.user_type}")
else:
    print("✓ USER deviceowner1 already exists")

# Create another regular USER (device owner)
if not User.objects.filter(username='deviceowner2').exists():
    user2 = User.objects.create_user(
        username='deviceowner2',
        email='owner2@test.com',
        password='test123',
        first_name='Jane',
        last_name='Smith'
    )
    print(f"✓ Created USER: {user2.username} - {user2.userprofile.user_type}")
else:
    print("✓ USER deviceowner2 already exists")

# Create an ADMIN (staff/installer)
if not User.objects.filter(username='installer1').exists():
    admin1 = User.objects.create_user(
        username='installer1',
        email='installer1@test.com',
        password='test123',
        first_name='Mike',
        last_name='Installer',
        is_staff=True
    )
    print(f"✓ Created ADMIN: {admin1.username} - {admin1.userprofile.user_type}")
else:
    print("✓ ADMIN installer1 already exists")

print("=" * 60)
print("CURRENT USER TYPES:")
print("=" * 60)

for user in User.objects.all():
    try:
        profile = user.userprofile
        print(f"  {user.username:20} -> {profile.user_type:10} (staff={user.is_staff}, super={user.is_superuser})")
    except UserProfile.DoesNotExist:
        print(f"  {user.username:20} -> NO PROFILE (staff={user.is_staff}, super={user.is_superuser})")

print("=" * 60)
print(f"Total users: {User.objects.count()}")
print(f"MASTER users: {UserProfile.objects.filter(user_type='MASTER').count()}")
print(f"ADMIN users: {UserProfile.objects.filter(user_type='ADMIN').count()}")
print(f"USER type users: {UserProfile.objects.filter(user_type='USER').count()}")
print("=" * 60)
