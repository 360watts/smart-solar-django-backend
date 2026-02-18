#!/usr/bin/env python
"""
Run Django migrations against the Supabase database.
Credentials are read from the .env file — never hardcode them here.
"""
import os
import sys
from urllib.parse import urlparse

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')

# Load DATABASE_URL from .env via python-decouple
from decouple import config

DATABASE_URL = config('DATABASE_URL', default='')
if not DATABASE_URL:
    print("ERROR: DATABASE_URL is not set in .env")
    sys.exit(1)

os.environ['DATABASE_URL'] = DATABASE_URL

if __name__ == '__main__':
    print("=" * 60)
    print("Testing database connection...")
    print("=" * 60)

    # Test raw connection first — parse URL so no credentials appear in source
    try:
        parsed = urlparse(DATABASE_URL)
        import psycopg2
        conn = psycopg2.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            user=parsed.username,
            password=parsed.password,
            dbname=parsed.path.lstrip('/'),
            sslmode='require'
        )
        cur = conn.cursor()
        cur.execute('SELECT version();')
        version = cur.fetchone()[0]
        print(f"Connected! PostgreSQL: {version[:50]}...")
        conn.close()
        print("Raw connection test: SUCCESS")
    except Exception as e:
        print(f"Raw connection test FAILED: {e}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("Running Django migrations...")
    print("=" * 60)

    # Setup Django
    import django
    django.setup()

    from django.core.management import call_command
    from django.db import connection

    # Show migration status
    print("\nMigration status BEFORE:")
    call_command('showmigrations', '--list')

    # Run migrations
    print("\n" + "-" * 40)
    print("Applying migrations...")
    print("-" * 40)
    call_command('migrate', '--verbosity=2')

    # Show final status
    print("\n" + "=" * 60)
    print("Migration status AFTER:")
    call_command('showmigrations', '--list')

    # Show tables created
    print("\n" + "=" * 60)
    print("Tables in database:")
    print("=" * 60)
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """)
        tables = cursor.fetchall()
        for t in tables:
            print(f"  - {t[0]}")

    print("\n" + "=" * 60)
    print("MIGRATIONS COMPLETE!")
    print("=" * 60)
