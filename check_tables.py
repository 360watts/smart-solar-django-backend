import os
import django

# Force use of Supabase database
os.environ['DATABASE_URL'] = 'postgres://postgres.gradxxhofbryazulajfy:3K2okENJGWtk3qH6@aws-1-ap-south-1.pooler.supabase.com:6543/postgres?sslmode=require'
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

from django.db import connection

cursor = connection.cursor()

print("=== Checking Supabase Production Database ===\n")

# Check tables
cursor.execute("""
    SELECT tablename 
    FROM pg_tables 
    WHERE schemaname='public' 
    AND tablename LIKE 'api_%' 
    ORDER BY tablename;
""")

print("Tables in database:")
for row in cursor.fetchall():
    print(f"  ✓ {row[0]}")

# Check migrations
cursor.execute("""
    SELECT app, name 
    FROM django_migrations 
    WHERE app = 'api'
    ORDER BY id;
""")

print("\nApplied migrations:")
for row in cursor.fetchall():
    print(f"  ✓ {row[1]}")

print("\n" + "="*50)
