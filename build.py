#!/usr/bin/env python
import os
import sys
import subprocess
from pathlib import Path

# Set the Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')

# Install requirements if needed (for Vercel)
try:
    import psycopg2
except ImportError:
    print("Installing psycopg2-binary...")
    subprocess.run([sys.executable, '-m', 'pip', 'install', 'psycopg2-binary'], check=True)

# Run migrations using manage.py
result = subprocess.run([
    sys.executable, 'manage.py', 'migrate', '--run-syncdb'
], cwd=Path(__file__).resolve().parent, capture_output=True, text=True)

if result.returncode != 0:
    print("Migration failed:")
    print(result.stderr)
    sys.exit(1)
else:
    print("Migrations completed successfully")
    print(result.stdout)

# Collect static files so Vercel has a build output directory
collectstatic = subprocess.run([
    sys.executable, 'manage.py', 'collectstatic', '--noinput'
], cwd=Path(__file__).resolve().parent, capture_output=True, text=True)

if collectstatic.returncode != 0:
    print("Collectstatic failed:")
    print(collectstatic.stderr)
    sys.exit(1)
else:
    print("Collectstatic completed successfully")
    print(collectstatic.stdout)
