# Environment Setup Guide

## ⚠️ IMPORTANT: Never Commit `.env` Files

This guide explains how to properly set up your local environment without exposing credentials.

---

## Quick Setup

### 1. Clone the Repository
```bash
git clone https://github.com/360watts/smart-solar-django-backend.git
cd smart-solar-django-backend
```

### 2. Create Your Local `.env` File
```bash
# Copy the template
cp .env.example .env

# Edit with your local credentials
nano .env  # or use your favorite editor
```

### 3. Fill in Your Credentials
Open `.env` and update with your actual values:

```dotenv
# Django Configuration
DEBUG=True
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=localhost,127.0.0.1

# CORS Configuration
CORS_ALLOW_ALL_ORIGINS=True
CORS_ALLOWED_ORIGINS=http://localhost:3000

# Database Configuration
# Option 1: Remote PostgreSQL (Production/Supabase)
DATABASE_URL=postgresql://username:password@host:port/database

# Option 2: Local PostgreSQL
DATABASE_POSTGRES_HOST=localhost
DATABASE_POSTGRES_PORT=5432
DATABASE_POSTGRES_DATABASE=smart_solar
DATABASE_POSTGRES_USER=postgres
DATABASE_POSTGRES_PASSWORD=your-db-password
```

### 4. Verify `.env` is NOT Tracked by Git
```bash
git status
# You should NOT see `.env` in the output
# If you do, you've accidentally committed it - see "Fixing Accidents" below
```

---

## Database Setup

### For Local Development (SQLite)
No additional setup needed - Django will create `db.sqlite3` automatically.

### For Local PostgreSQL
```bash
# Install PostgreSQL
# macOS: brew install postgresql
# Ubuntu: sudo apt-get install postgresql
# Windows: Download from postgresql.org

# Create a database
psql -U postgres
CREATE DATABASE smart_solar;
CREATE USER smart_solar_user WITH PASSWORD 'your-password';
ALTER ROLE smart_solar_user SET client_encoding TO 'utf8';
ALTER ROLE smart_solar_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE smart_solar_user SET default_transaction_deferrable TO on;
ALTER ROLE smart_solar_user SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE smart_solar TO smart_solar_user;
\q
```

Update `.env`:
```dotenv
DATABASE_POSTGRES_HOST=localhost
DATABASE_POSTGRES_PORT=5432
DATABASE_POSTGRES_DATABASE=smart_solar
DATABASE_POSTGRES_USER=smart_solar_user
DATABASE_POSTGRES_PASSWORD=your-password
```

### For Supabase (Production/Remote)
1. Create a project at https://supabase.com
2. Go to Project Settings → Database
3. Copy the connection URL
4. Update `.env`:
```dotenv
DATABASE_URL=postgresql://postgres.xxxxx:password@aws-x-region.pooler.supabase.com:6543/postgres?sslmode=require
```

---

## Running the Application

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Run Migrations
```bash
python manage.py migrate
```

### Create Superuser (Admin)
```bash
python manage.py createsuperuser
```

### Start Development Server
```bash
python manage.py runserver
# or with SSL for HTTPS
python manage.py runsslserver
```

---

## Fixing Accidents

### If You Accidentally Committed `.env`:

**Step 1: Remove from staging (if not pushed)**
```bash
git reset HEAD .env
```

**Step 2: Remove from history (if already pushed)**
```bash
# Using git filter-branch
git filter-branch --tree-filter 'rm -f .env' -- --all
git push origin --force --all

# Then, notify all team members to re-clone
```

**Step 3: Invalidate Compromised Credentials**
- Change your database password
- Rotate any exposed API keys
- Update deployment variables

---

## Security Checklist

✅ `.env` is in `.gitignore`  
✅ `.env` is NOT committed to git  
✅ `.env.example` exists and is committed (without credentials)  
✅ Never paste credentials in chat, emails, or documentation  
✅ Use unique passwords for each environment (dev, staging, production)  
✅ Rotate credentials regularly  
✅ Use strong, randomly generated passwords  

---

## Environment Variables Reference

| Variable | Description | Example |
|---|---|---|
| `DEBUG` | Django debug mode (False for production) | `False` |
| `SECRET_KEY` | Django secret key for security | `django-insecure-...` |
| `ALLOWED_HOSTS` | Allowed domain names | `localhost,127.0.0.1,example.com` |
| `CORS_ALLOWED_ORIGINS` | CORS whitelist for frontend | `http://localhost:3000` |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://user:pass@host:5432/db` |
| `DATABASE_POSTGRES_*` | Individual PostgreSQL settings | See above |

---

## Useful Commands

```bash
# Check git status
git status

# View what will be pushed
git diff origin/main

# Show tracked files
git ls-files

# Show ignored files
git status --ignored

# Test environment loading
python -c "from decouple import config; print(config('DEBUG'))"
```

---

## Troubleshooting

### Error: "Could not read .env file"
- Ensure `.env` exists in the project root
- Check file permissions: `chmod 644 .env`
- Verify you're in the correct directory

### Error: "Database connection refused"
- Check DATABASE_* variables in `.env`
- Verify PostgreSQL is running
- Test connection: `psql -U username -d database -h localhost`

### Error: "Module not found"
- Ensure requirements are installed: `pip install -r requirements.txt`
- Check Python version: `python --version` (requires 3.8+)

---

## Team Communication

If you accidentally commit secrets:
1. **IMMEDIATELY** notify the team
2. Rotate all compromised credentials
3. Force-push corrected history
4. All team members must re-clone

---

**Last Updated:** 2026-02-04  
**Status:** Active
