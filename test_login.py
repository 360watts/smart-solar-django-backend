import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken

username = 'admin'
password = 'admin'  # Use your actual password

user = authenticate(username=username, password=password)

if user:
    refresh = RefreshToken.for_user(user)
    response_data = {
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'is_staff': user.is_staff,
            'is_superuser': user.is_superuser,
        },
        'tokens': {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }
    }
    print("\n=== LOGIN RESPONSE ===")
    print(json.dumps(response_data['user'], indent=2))
    print(f"\nis_staff: {user.is_staff}")
    print(f"is_superuser: {user.is_superuser}")
else:
    print("Authentication failed")
