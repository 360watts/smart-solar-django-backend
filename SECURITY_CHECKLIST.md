# 🔒 Production Security Checklist

## ✅ Completed
- [x] Removed CORS_ALLOW_ALL_ORIGINS
- [x] Added explicit CORS whitelist

## 🚨 CRITICAL - Must Complete Before Production

### 1. Environment Variables
- [ ] Set secure SECRET_KEY in production (not django-insecure-change-me)
- [ ] Set DEVICE_JWT_SECRET separately from SECRET_KEY
- [ ] Set DEBUG=False in production environment
- [ ] Configure DATABASE_URL for production database
- [ ] Set ALLOWED_HOSTS to production domain only

### 2. API Authentication
**CRITICAL: Many endpoints use @permission_classes([AllowAny])**

Review and secure these endpoints in `api/views.py`:
- [ ] Line 34: `provision` - Add device authentication via claim nonce validation
- [ ] Line 86: `gateway_config` - Add JWT device token validation
- [ ] Line 116: `push_config` - Add JWT device token validation  
- [ ] Line 160: `alerts` - Add JWT device token validation
- [ ] Line 172: `telemetry_ingest` - Add JWT device token validation
- [ ] Line 182: `telemetry_latest` - Requires authentication or device token
- [ ] Line 355: `register_user` - Consider adding CAPTCHA
- [ ] Line 416: `login_user` - Add rate limiting (3-5 attempts per minute)
- [ ] Line 1302: Review if AllowAny is appropriate

**Recommended Solution:**
```python
from rest_framework.permissions import IsAuthenticated

# For device endpoints, create custom permission:
class IsAuthenticatedDevice(BasePermission):
    def has_permission(self, request, view):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return False
        try:
            token = auth_header.replace('Bearer ', '')
            payload = jwt.decode(token, DEVICE_JWT_SECRET, algorithms=['HS256'])
            return payload.get('type') == 'device'
        except:
            return False
```

### 3. Delete Sensitive Files
- [ ] **DELETE** `test_login.py` - contains hardcoded credentials
- [ ] Review all `.py` files for hardcoded passwords/tokens
- [ ] Add `test_login.py` to `.gitignore`

### 4. Rate Limiting
- [ ] Install django-ratelimit: `pip install django-ratelimit`
- [ ] Add rate limiting to login endpoint (3 attempts/min)
- [ ] Add rate limiting to registration (1 user/5min per IP)
- [ ] Add rate limiting to telemetry endpoints (100 req/min per device)

### 5. Input Validation
- [ ] Review all serializers for proper validation
- [ ] Add max_length constraints to all text fields
- [ ] Validate slave_id range (1-247) in serializer not just frontend
- [ ] Sanitize user input in device names and labels

### 6. Database Security
- [ ] Ensure PostgreSQL uses SSL (sslmode=require) ✓ Already configured
- [ ] Use separate database users with minimal privileges
- [ ] Enable PostgreSQL query logging for production monitoring
- [ ] Regular database backups configured

### 7. HTTPS/SSL
- [ ] Verify SSL certificates are valid
- [ ] Test HSTS headers are working
- [ ] Ensure all resources load over HTTPS (no mixed content)

### 8. Frontend Security
- [ ] Consider moving JWT tokens from localStorage to httpOnly cookies
- [ ] Add Content Security Policy headers
- [ ] Implement XSS protection in user-generated content
- [ ] Sanitize any data rendered from API

### 9. Monitoring & Logging
- [ ] Set up error monitoring (Sentry, Rollbar, etc.)
- [ ] Configure log rotation for production
- [ ] Set up alerts for failed login attempts
- [ ] Monitor API rate limiting violations

### 10. Additional Hardening
- [ ] Enable Django Admin two-factor authentication
- [ ] Rotate JWT tokens regularly (implement refresh token flow)
- [ ] Add API versioning for breaking changes
- [ ] Implement request signature verification for device endpoints
- [ ] Add CAPTCHA to registration/login after failed attempts

## 📋 Pre-Deployment Commands

```bash
# Backend
cd smart-solar-django-backend-main

# Install additional security packages
pip install django-ratelimit django-defender

# Delete test files
rm test_login.py

# Verify environment variables
python -c "from decouple import config; print('SECRET_KEY length:', len(config('SECRET_KEY')))"

# Run security checks
python manage.py check --deploy

# Collect static files
python manage.py collectstatic --noinput

# Run migrations
python manage.py migrate
```

## 🔐 Environment Variables Template

Create `.env` file (NEVER commit this):

```env
# Django Core
SECRET_KEY=<generate-random-64-char-string>
DEVICE_JWT_SECRET=<different-random-64-char-string>
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# Database
DATABASE_URL=postgresql://user:password@host:5432/dbname

# CORS
CORS_ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

# Optional
SENTRY_DSN=<your-sentry-dsn>
```

## 🧪 Security Testing

Before deployment:
```bash
# Test with OWASP ZAP or similar
# Check for SQL injection vulnerabilities
# Test authentication bypass attempts
# Verify rate limiting works
# Test CORS configuration
```

## 📞 Incident Response Plan
- [ ] Document who to contact for security issues
- [ ] Prepare rollback procedure
- [ ] Have database backup restore procedure ready
- [ ] Document how to rotate compromised keys

---

**Status**: ⚠️ NOT READY FOR PRODUCTION  
**Blocking Issues**: 7 critical items  
**Last Updated**: 2026-02-10
