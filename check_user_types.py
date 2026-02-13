"""
Test script to verify user_type migration
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

from api.models import UserProfile
from django.contrib.auth.models import User

print("=" * 60)
print("USER TYPES AFTER MIGRATION")
print("=" * 60)

for user in User.objects.all():
    try:
        profile = user.userprofile
        print(f"✓ {user.username:20} -> {profile.user_type:10} (staff={user.is_staff}, super={user.is_superuser})")
    except UserProfile.DoesNotExist:
        print(f"✗ {user.username:20} -> NO PROFILE (staff={user.is_staff}, super={user.is_superuser})")

print("=" * 60)
print(f"Total users: {User.objects.count()}")
print(f"Users with profiles: {UserProfile.objects.count()}")
print(f"MASTER users: {UserProfile.objects.filter(user_type='MASTER').count()}")
print(f"ADMIN users: {UserProfile.objects.filter(user_type='ADMIN').count()}")
print(f"USER type users: {UserProfile.objects.filter(user_type='USER').count()}")
print("=" * 60)
