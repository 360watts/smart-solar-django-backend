import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

from django.contrib.auth.models import User

print("\n=== Updating Rajeev and Nancy to staff ===")

# Update rajeev to staff
rajeev = User.objects.filter(username__icontains='rajeev').first()
if rajeev:
    rajeev.is_staff = True
    rajeev.is_superuser = False
    rajeev.save()
    print(f"Updated {rajeev.username} - is_staff: {rajeev.is_staff}, is_superuser: {rajeev.is_superuser}")

# Check for nancy
nancy = User.objects.filter(username__icontains='nancy').first()
if nancy:
    nancy.is_staff = True
    nancy.is_superuser = False
    nancy.save()
    print(f"Updated {nancy.username} - is_staff: {nancy.is_staff}, is_superuser: {nancy.is_superuser}")
else:
    print("Nancy not found in database")

print("\n=== Current state after update ===")
for user in User.objects.all():
    print(f"Username: {user.username}, is_staff: {user.is_staff}, is_superuser: {user.is_superuser}")
