#!/usr/bin/env python
import os
import sys
import subprocess
from pathlib import Path


# Build script for Vercel
print("=== Vercel Build Script ===")

# Check if we should run migrations (only if database is accessible)
RUN_MIGRATIONS = os.getenv('RUN_MIGRATIONS_ON_BUILD', 'false').lower() == 'true'

if RUN_MIGRATIONS:
    # Run database migrations
    print("\n[1/2] Running database migrations...")
    try:
        subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"], check=True)
        print("✅ Migrations completed successfully")
    except subprocess.CalledProcessError as e:
        print(f"⚠️ Migration failed (continuing build): {e}")
        # Don't fail the build if migrations fail
else:
    print("\n[1/2] Skipping migrations (RUN_MIGRATIONS_ON_BUILD not set)")
    print("   Run migrations manually: vercel env pull && python manage.py migrate")

# Collect static files
print("\n[2/2] Collecting static files...")
try:
    subprocess.run([sys.executable, "manage.py", "collectstatic", "--noinput", "--clear"], check=True)
    print("✅ Static files collected successfully")
except subprocess.CalledProcessError as e:
    print(f"⚠️ Collectstatic failed (continuing): {e}")

print("\n✅ Build completed!")


