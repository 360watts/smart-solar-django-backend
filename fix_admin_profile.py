import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

from django.contrib.auth.models import User
from api.models import UserProfile

# Get admin user
admin = User.objects.filter(is_superuser=True).first()

if admin:
    print(f"Admin found: {admin.username}")
    print(f"Email: {admin.email}")
    print(f"First name: {admin.first_name}")
    print(f"Last name: {admin.last_name}")
    
    # Check if profile exists
    try:
        profile = admin.userprofile
        print(f"Profile exists: Yes")
        print(f"Mobile: {profile.mobile_number}")
        print(f"Address: {profile.address}")
    except UserProfile.DoesNotExist:
        print("Profile exists: No")
        print("Creating profile...")
        profile = UserProfile.objects.create(
            user=admin,
            mobile_number='',
            address=''
        )
        print("Profile created successfully!")
else:
    print("No admin user found!")
