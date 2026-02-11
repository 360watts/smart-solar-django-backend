#!/usr/bin/env python
"""
Script to run Django migrations
Use this locally or after Vercel deployment
"""
import os
import sys
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

# Import after Django setup
from django.core.management import call_command

print("=== Running Database Migrations ===\n")

try:
    # Show pending migrations
    print("Checking for pending migrations...\n")
    call_command('showmigrations', verbosity=1)
    
    print("\n" + "="*50)
    print("Applying migrations...")
    print("="*50 + "\n")
    
    # Run migrations
    call_command('migrate', verbosity=2, interactive=False)
    
    print("\n" + "="*50)
    print("✅ All migrations completed successfully!")
    print("="*50)
    
except Exception as e:
    print(f"\n❌ Migration failed: {e}")
    sys.exit(1)
