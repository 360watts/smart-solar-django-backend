"""
Quick setup script for Customer/Employee separation

This script checks prerequisites and guides you through the migration.
"""

import os
import sys

def check_python_version():
    """Ensure Python 3.8+"""
    if sys.version_info < (3, 8):
        print("❌ Python 3.8 or higher is required")
        return False
    print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    return True

def check_django():
    """Check if Django is installed"""
    try:
        import django
        print(f"✅ Django {django.get_version()} installed")
        return True
    except ImportError:
        print("❌ Django not installed. Run: pip install -r requirements.txt")
        return False

def check_database():
    """Check if database exists"""
    if os.path.exists('db.sqlite3'):
        print("✅ Database file found")
        return True
    else:
        print("⚠️  No database file found. Will be created on first migration.")
        return True

def main():
    print("=" * 70)
    print("SMART SOLAR - CUSTOMER/EMPLOYEE SEPARATION SETUP")
    print("=" * 70)
    print()
    
    print("Step 1: Checking prerequisites...")
    print("-" * 70)
    
    checks_passed = True
    checks_passed &= check_python_version()
    checks_passed &= check_django()
    checks_passed &= check_database()
    
    print()
    
    if not checks_passed:
        print("❌ Prerequisites not met. Please install required packages.")
        return
    
    print("=" * 70)
    print("MIGRATION STEPS")
    print("=" * 70)
    print()
    print("1️⃣  Backup your database:")
    print("    cp db.sqlite3 db.sqlite3.backup")
    print()
    print("2️⃣  Create Django migrations:")
    print("    python manage.py makemigrations")
    print()
    print("3️⃣  Apply migrations:")
    print("    python manage.py migrate")
    print()
    print("4️⃣  Migrate existing users to customers:")
    print("    python migrate_users_to_customers.py")
    print()
    print("5️⃣  Create admin user if needed:")
    print("    python manage.py createsuperuser")
    print()
    print("6️⃣  Start the server:")
    print("    python manage.py runserver")
    print()
    print("=" * 70)
    print("FRONTEND SETUP")
    print("=" * 70)
    print()
    print("1️⃣  Install dependencies:")
    print("    cd ../smart-solar-react-frontend-main")
    print("    npm install")
    print()
    print("2️⃣  Start development server:")
    print("    npm start")
    print()
    print("=" * 70)
    print()
    print("📖 For detailed instructions, see CUSTOMER_EMPLOYEE_MIGRATION.md")
    print()
    
    response = input("Would you like to start the migration now? (y/n): ")
    if response.lower() == 'y':
        print()
        print("Starting migration process...")
        print()
        
        # Backup database
        if os.path.exists('db.sqlite3'):
            print("📦 Creating database backup...")
            os.system('cp db.sqlite3 db.sqlite3.backup 2>/dev/null || copy db.sqlite3 db.sqlite3.backup')
            print("✅ Backup created: db.sqlite3.backup")
        
        print()
        print("🔄 Creating migrations...")
        os.system('python manage.py makemigrations')
        
        print()
        print("🔄 Applying migrations...")
        os.system('python manage.py migrate')
        
        print()
        print("=" * 70)
        print("✅ Migration setup complete!")
        print("=" * 70)
        print()
        print("Next step: Run the data migration script")
        print("    python migrate_users_to_customers.py")
        print()

if __name__ == "__main__":
    main()
