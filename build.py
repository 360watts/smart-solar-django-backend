#!/usr/bin/env python
import os
import sys
import subprocess
from pathlib import Path


# Build script for Vercel: run migrations and collectstatic
print("=== Vercel Build Script ===")

# Run database migrations
print("\n[1/2] Running database migrations...")
try:
    subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"], check=True)
    print("✅ Migrations completed successfully")
except subprocess.CalledProcessError as e:
    print(f"❌ Migration failed: {e}")
    sys.exit(1)

# Collect static files
print("\n[2/2] Collecting static files...")
try:
    subprocess.run([sys.executable, "manage.py", "collectstatic", "--noinput"], check=True)
    print("✅ Static files collected successfully")
except subprocess.CalledProcessError as e:
    print(f"❌ Collectstatic failed: {e}")
    sys.exit(1)

print("\n✅ Build completed successfully!")

