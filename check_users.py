import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

from django.contrib.auth.models import User

print("\n=== ALL USERS ===")
for user in User.objects.all():
    print(f"ID: {user.id}, Username: {user.username}, is_staff: {user.is_staff}, is_superuser: {user.is_superuser}")
