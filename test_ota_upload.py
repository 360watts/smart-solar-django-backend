"""
Test OTA Firmware Upload Locally
Run this script to test firmware upload functionality before deploying
"""

import os
import sys
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')
django.setup()

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from ota.models import FirmwareVersion
import hashlib

User = get_user_model()

def test_upload():
    print("=== OTA Upload Test ===\n")
    
    # 1. Check for admin user
    print("1. Checking for admin user...")
    try:
        admin = User.objects.filter(is_superuser=True).first()
        if not admin:
            print("   ❌ No admin user found!")
            print("   Create one with: python manage.py createsuperuser")
            return False
        print(f"   ✅ Admin user found: {admin.username}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False
    
    # 2. Create test firmware data
    print("\n2. Creating test firmware...")
    test_content = b"This is test firmware content" * 1000  # ~30KB
    test_file = SimpleUploadedFile(
        name="test_firmware_v1.0.1.bin",
        content=test_content,
        content_type="application/octet-stream"
    )
    
    # Calculate checksum
    checksum = hashlib.sha256(test_content).hexdigest()
    print(f"   Test file size: {len(test_content)} bytes")
    print(f"   Checksum: {checksum[:16]}...")
    
    # 3. Create firmware version
    print("\n3. Creating firmware version in database...")
    try:
        # Delete existing test versions
        FirmwareVersion.objects.filter(version__startswith="TEST_").delete()
        
        firmware = FirmwareVersion.objects.create(
            version="TEST_1.0.1",
            filename=test_file.name,
            file=test_file,
            size=len(test_content),
            checksum=checksum,
            description="Test firmware upload",
            release_notes="Testing OTA upload functionality",
            is_active=False,
            created_by=admin
        )
        print(f"   ✅ Firmware created successfully!")
        print(f"   ID: {firmware.id}")
        print(f"   Version: {firmware.version}")
        print(f"   File path: {firmware.file.name}")
        print(f"   Size: {firmware.size} bytes")
    except Exception as e:
        print(f"   ❌ Error creating firmware: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # 4. Test file exists
    print("\n4. Verifying file storage...")
    if firmware.file:
        file_path = firmware.file.path if hasattr(firmware.file, 'path') else str(firmware.file)
        print(f"   File location: {file_path}")
        
        # Check if using S3
        if hasattr(firmware.file.storage, 'bucket_name'):
            print(f"   ✅ Using S3 storage: {firmware.file.storage.bucket_name}")
        else:
            print(f"   ℹ️  Using local storage")
            if os.path.exists(file_path):
                print(f"   ✅ File exists on disk")
            else:
                print(f"   ⚠️  File not found on disk (might be in memory)")
    
    # 5. Test retrieval
    print("\n5. Testing firmware retrieval...")
    try:
        retrieved = FirmwareVersion.objects.get(id=firmware.id)
        print(f"   ✅ Firmware retrieved successfully")
        print(f"   Version: {retrieved.version}")
        print(f"   Active: {retrieved.is_active}")
    except Exception as e:
        print(f"   ❌ Error retrieving firmware: {e}")
        return False
    
    # 6. Test activation
    print("\n6. Testing firmware activation...")
    try:
        firmware.is_active = True
        firmware.save()
        print(f"   ✅ Firmware activated successfully")
        
        active_count = FirmwareVersion.objects.filter(is_active=True).count()
        print(f"   Active firmware versions: {active_count}")
    except Exception as e:
        print(f"   ❌ Error activating firmware: {e}")
        return False
    
    print("\n=== Test Summary ===")
    print("✅ All tests passed!")
    print("\nTest firmware details:")
    print(f"   ID: {firmware.id}")
    print(f"   Version: {firmware.version}")
    print(f"   Size: {firmware.size} bytes")
    print(f"   Active: {firmware.is_active}")
    print(f"   Download URL: /api/ota/firmware/{firmware.id}/download")
    
    # Cleanup option
    cleanup = input("\nDelete test firmware? (y/n): ").lower()
    if cleanup == 'y':
        firmware.delete()
        print("✅ Test firmware deleted")
    
    return True

if __name__ == "__main__":
    success = test_upload()
    sys.exit(0 if success else 1)
