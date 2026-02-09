# How to Add DEVICE_JWT_SECRET to Vercel and Run Migrations

## Step 1: Generate a Secure DEVICE_JWT_SECRET

Generate a strong random secret key for device JWT tokens. Run this command:

```bash
# On Windows (PowerShell)
python -c "import secrets; print(secrets.token_urlsafe(32))"

# On Mac/Linux
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Example output:**
```
AbCdEfGhIjKlMnOpQrStUvWxYz1234567890_-AbCd
```

Copy this value - you'll need it in the next step.

---

## Step 2: Add to Vercel Environment Variables

### Option A: Using Vercel Dashboard (Recommended)

1. Go to [Vercel Dashboard](https://vercel.com/dashboard)
2. Select your **smart-solar-django-backend** project
3. Click **Settings** → **Environment Variables**
4. Click **Add New**
5. Fill in:
   - **Name:** `DEVICE_JWT_SECRET`
   - **Value:** (paste the secret you generated)
   - **Environments:** Select all (Production, Preview, Development)
6. Click **Save**

### Option B: Using Vercel CLI

```bash
# Install Vercel CLI (if not already installed)
npm install -g vercel

# Login to Vercel
vercel login

# Add the environment variable
vercel env add DEVICE_JWT_SECRET

# You'll be prompted to enter:
# - The secret value
# - Which environments to apply it to (select all)
```

---

## Step 3: Run Migrations on Vercel

### Option A: Using Vercel CLI with Build Hook

```bash
# SSH into your Vercel deployment (if using hobby tier)
# Note: This requires Vercel premium. For free tier, use Option B.

vercel shell

# Then run:
python manage.py migrate
```

### Option B: Add Migration Command to Vercel (Recommended)

Update your **vercel.json** to run migrations automatically on deployment:

```json
{
  "buildCommand": "python manage.py collectstatic --noinput && python manage.py migrate",
  "outputDirectory": "."
}
```

### Option C: Run Locally Against Vercel Database

If you have the `DATABASE_URL` for Vercel:

```bash
# Set the environment variable
$env:DATABASE_URL = "postgresql://user:pass@host:port/db"  # PowerShell
# or
export DATABASE_URL="postgresql://user:pass@host:port/db"  # Bash

# Run migrations
python manage.py migrate

# Check migration status
python manage.py showmigrations api
```

---

## Step 4: Verify Everything Works

### Check 1: Health Check Endpoint

```bash
curl https://your-api.vercel.app/api/health-check/
```

**Expected response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-01-01T00:00:00Z",
  "version": "1.0.0",
  "checks": {
    "database": {"status": "up"},
    "cache": {"status": "not_configured"}
  }
}
```

### Check 2: API Documentation

Visit these URLs in your browser:
- `https://your-api.vercel.app/api/docs/` (Swagger UI)
- `https://your-api.vercel.app/api/redoc/` (ReDoc)

### Check 3: Alert Endpoint

```bash
curl -X GET https://your-api.vercel.app/api/alerts/manage/ \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

---

## Step 5: Test Device Provisioning

The new DEVICE_JWT_SECRET will be used automatically when ESP32 devices provision:

```bash
curl -X POST https://your-api.vercel.app/api/devices/provision/ \
  -H "Content-Type: application/json" \
  -d '{
    "hwId": "A020A6123456",
    "model": "esp32 wroom",
    "claimNonce": "IM_YOUR_DEVICE"
  }'
```

**Expected response:**
```json
{
  "status": "success",
  "deviceId": "ABC123DEF456",
  "provisionedAt": "2025-01-01T00:00:00Z",
  "credentials": {
    "type": "jwt",
    "secret": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "expiresIn": 31536000
  }
}
```

---

## Environment Variables Summary

Your Vercel project should now have these environment variables:

| Variable | Value | Example |
|----------|-------|---------|
| `SECRET_KEY` | Django secret key | `django-insecure-abc123...` |
| `DATABASE_URL` | PostgreSQL connection | `postgresql://user:pass@host/db` |
| `DEVICE_JWT_SECRET` | Device JWT secret | `AbCdEfGhIjKlMnOp...` |
| `DEBUG` | False | `False` |
| `CORS_ALLOWED_ORIGINS` | Frontend URLs | `https://smart-solar-react-frontend.vercel.app` |
| `ALLOWED_HOSTS` | Allowed domains | `your-api.vercel.app,.vercel.app` |

---

## Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'drf_spectacular'"

**Solution:** The build must run `pip install -r requirements.txt` first. Update `vercel.json`:

```json
{
  "buildCommand": "pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate"
}
```

### Issue: "DEVICE_JWT_SECRET not found"

**Solution:** Make sure you've set it in Vercel Environment Variables and redeployed:

```bash
vercel deploy --prod
```

### Issue: Migrations fail with "table already exists"

**Solution:** Migration is idempotent. If the Alert table already exists:

```bash
# Check what migrations have been run
python manage.py showmigrations api

# If needed, fake the migration
python manage.py migrate api 0005_add_alert_model --fake
```

---

## Additional Resources

- [Vercel Environment Variables Docs](https://vercel.com/docs/concepts/projects/environment-variables)
- [Django Migrations Documentation](https://docs.djangoproject.com/en/5.2/topics/migrations/)
- [drf-spectacular Documentation](https://drf-spectacular.readthedocs.io/)

---

*Last Updated: February 4, 2026*
