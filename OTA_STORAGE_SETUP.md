# OTA Firmware Storage Setup

## Overview

The OTA system requires persistent file storage for firmware binaries. Since Vercel is a serverless platform with ephemeral filesystems, you need to configure cloud storage for production deployments.

## Storage Options

### Option 1: AWS S3 (Recommended for Production)

AWS S3 provides reliable, scalable object storage perfect for firmware files.

#### Setup Steps:

1. **Create AWS S3 Bucket**
   - Go to AWS Console → S3
   - Click "Create bucket"
   - Bucket name: `smart-solar-firmware` (or your preferred name)
   - Region: Choose closest to your users (e.g., `us-east-1`)
   - Block Public Access: Uncheck "Block all public access" (firmware files need to be downloadable)
   - Enable versioning (optional but recommended)
   - Create bucket

2. **Configure CORS for S3 Bucket**
   - Select your bucket → Permissions → CORS
   - Add this configuration:
   ```json
   [
     {
       "AllowedHeaders": ["*"],
       "AllowedMethods": ["GET", "HEAD", "PUT", "POST"],
       "AllowedOrigins": [
         "https://smart-solar-react-frontend.vercel.app",
         "https://smart-solar-django-backend.vercel.app"
       ],
       "ExposeHeaders": ["ETag"]
     }
   ]
   ```

3. **Create IAM User for Django**
   - Go to IAM → Users → Add user
   - User name: `smart-solar-django-s3`
   - Access type: "Programmatic access"
   - Attach existing policy: `AmazonS3FullAccess` (or create custom policy below)
   - Save the **Access Key ID** and **Secret Access Key**

4. **Custom IAM Policy (More Secure)**
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "s3:PutObject",
           "s3:GetObject",
           "s3:DeleteObject",
           "s3:ListBucket"
         ],
         "Resource": [
           "arn:aws:s3:::smart-solar-firmware/*",
           "arn:aws:s3:::smart-solar-firmware"
         ]
       }
     ]
   }
   ```

5. **Configure Vercel Environment Variables**
   - Go to Vercel Dashboard → Your Project → Settings → Environment Variables
   - Add these variables:
   
   ```
   USE_S3=True
   AWS_ACCESS_KEY_ID=<your-access-key-id>
   AWS_SECRET_ACCESS_KEY=<your-secret-access-key>
   AWS_STORAGE_BUCKET_NAME=smart-solar-firmware
   AWS_S3_REGION_NAME=us-east-1
   ```

6. **Redeploy on Vercel**
   - Push changes to GitHub or trigger manual deployment
   - Verify S3 is active by checking logs for "Using S3 storage: smart-solar-firmware"

### Option 2: Local Development Storage

For local testing, the system uses Django's default FileSystemStorage:

```bash
# Create media directory
mkdir media
mkdir media/firmware

# Files will be stored in: smart-solar-django-backend/media/firmware/
```

**Important**: Local storage does NOT work on Vercel production. Always use S3 for production.

## Frontend Configuration

No changes needed! The backend returns full download URLs automatically:

- **Local**: `http://localhost:8000/media/firmware/file.bin`
- **S3**: `https://smart-solar-firmware.s3.amazonaws.com/media/file.bin`

## Testing Upload Functionality

### Local Testing:

1. Start Django server:
   ```bash
   python manage.py runserver
   ```

2. Create superuser if not exists:
   ```bash
   python manage.py createsuperuser
   ```

3. Test upload with curl:
   ```bash
   # Login to get JWT token
   curl -X POST http://localhost:8000/api/login/ \
     -H "Content-Type: application/json" \
     -d '{"username": "admin", "password": "your-password"}'

   # Upload firmware (replace YOUR_TOKEN)
   curl -X POST http://localhost:8000/api/ota/firmware/create/ \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -F "file=@path/to/firmware.bin" \
     -F "version=1.0.1" \
     -F "description=Test firmware" \
     -F "is_active=false"
   ```

### Production Testing:

1. Login to web app: https://smart-solar-react-frontend.vercel.app/login
2. Navigate to OTA management page
3. Fill upload form:
   - **Version**: `1.0.1` or `0x00020000`
   - **File**: Select your `.bin` firmware file
   - **Description**: Brief description
   - **Release Notes**: Changelog (optional)
   - **Is Active**: Check to make it available to devices
4. Click "Upload"
5. Verify file appears in firmware list
6. Check S3 bucket to confirm file was uploaded

## Troubleshooting

### "No firmware file provided" Error
- Ensure `Content-Type: multipart/form-data` header is set
- Verify file field name is `file`
- Check file size doesn't exceed limits (default: 50MB Django limit)

### "Firmware version already exists" Error
- Each version must be unique
- Delete old version first or use a different version string

### Files not persisting on Vercel
- Check `USE_S3=True` is set in Vercel environment variables
- Verify AWS credentials are correct
- Check Django logs for S3 connection errors
- Confirm S3 bucket permissions allow uploads

### Device can't download firmware
- Verify firmware `is_active=True`
- Check S3 bucket public access settings
- Confirm CORS configuration allows device URLs
- Test download URL directly in browser

### Django logs show "Production mode without S3 storage" warning
- Set `USE_S3=True` in environment variables
- Add AWS credentials to Vercel environment
- Redeploy application

## Cost Estimation (AWS S3)

For typical usage:
- **Storage**: $0.023/GB per month (first 50TB)
- **Data Transfer**: First 1GB free, then $0.09/GB
- **Requests**: $0.0004 per 1,000 GET requests

Example: 100 devices, 2MB firmware, 5 updates/year:
- Storage: ~2MB × 5 versions = 10MB = **~$0.01/month**
- Transfer: 100 devices × 5 updates × 2MB = 1GB = **Free to $0.09**
- Total: **<$1/month**

## Alternative: Vercel Blob Storage

If you prefer Vercel's native solution:

1. Install package:
   ```bash
   pip install vercel-blob-sdk
   ```

2. Configure in settings.py:
   ```python
   if config('VERCEL_BLOB_TOKEN', default=''):
       # Use Vercel Blob Storage
       DEFAULT_FILE_STORAGE = 'path.to.custom.VercelBlobStorage'
   ```

3. Add to Vercel environment:
   ```
   VERCEL_BLOB_TOKEN=<from-vercel-dashboard>
   ```

*Note: Vercel Blob requires custom storage backend implementation. S3 is recommended for simplicity.*

## Security Best Practices

1. **Never commit AWS credentials** to code or version control
2. Use **environment variables** for all sensitive data
3. Implement **IAM least-privilege policies** (custom policy above)
4. Enable **S3 bucket versioning** for rollback capability
5. Set up **CloudWatch alerts** for unusual S3 activity
6. Rotate AWS access keys every 90 days
7. Use **presigned URLs** for temporary device access (future enhancement)

## Next Steps

After storage is configured:
1. Upload your first firmware via web UI
2. Activate the firmware
3. Update device firmware to use correct OTA URL: `/api/ota/devices/{id}/check`
4. Test OTA update from STM32 device
5. Monitor update logs in Django admin
