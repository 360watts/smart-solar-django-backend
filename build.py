#!/usr/bin/env python
import os
import sys
import subprocess
from pathlib import Path

# Set the Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')

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