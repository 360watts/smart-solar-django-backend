"""
Test API endpoints for user filtering
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from api.models import UserProfile
from rest_framework_simplejwt.tokens import RefreshToken

# Get a token for testing (use admin user)
admin = User.objects.filter(username='admin').first()
if not admin:
    print("Admin user not found!")
    exit(1)

print(f"Testing with user: {admin.username}")
print("=" * 60)

# Create token
refresh = RefreshToken.for_user(admin)
token = str(refresh.access_token)

client = Client()
headers = {'HTTP_AUTHORIZATION': f'Bearer {token}'}

print("\n1. Testing /api/users/ (default - should return USER type only)")
response = client.get('/api/users/', **headers)
if response.status_code == 200:
    data = response.json()
    print(f"   Found {len(data)} users:")
    for user in data:
        print(f"   - {user['username']:20} ({user.get('user_type', 'N/A')})")
else:
    print(f"   Error: {response.status_code}")

print("\n2. Testing /api/users/?user_type=ADMIN (should return ADMIN type only)")
response = client.get('/api/users/?user_type=ADMIN', **headers)
if response.status_code == 200:
    data = response.json()
    print(f"   Found {len(data)} users:")
    for user in data:
        print(f"   - {user['username']:20} ({user.get('user_type', 'N/A')})")
else:
    print(f"   Error: {response.status_code}")

print("\n3. Testing /api/users/?user_type=MASTER (should return MASTER type only)")
response = client.get('/api/users/?user_type=MASTER', **headers)
if response.status_code == 200:
    data = response.json()
    print(f"   Found {len(data)} users:")
    for user in data:
        print(f"   - {user['username']:20} ({user.get('user_type', 'N/A')})")
else:
    print(f"   Error: {response.status_code}")

print("\n4. Testing /api/users/device-owners/ (should return USER type only)")
response = client.get('/api/users/device-owners/', **headers)
if response.status_code == 200:
    data = response.json()
    print(f"   Found {len(data)} users:")
    for user in data:
        print(f"   - {user['username']:20} ({user.get('user_type', 'N/A')})")
else:
    print(f"   Error: {response.status_code}")

print("\n" + "=" * 60)
print("DATABASE STATE:")
print("=" * 60)
for user in User.objects.all():
    try:
        profile = user.userprofile
        print(f"{user.username:20} -> {profile.user_type:10} (staff={user.is_staff}, super={user.is_superuser})")
    except UserProfile.DoesNotExist:
        print(f"{user.username:20} -> NO PROFILE (staff={user.is_staff}, super={user.is_superuser})")
print("=" * 60)
