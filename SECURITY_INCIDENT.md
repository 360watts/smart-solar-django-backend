# SECURITY INCIDENT REPORT

## ⚠️ CRITICAL: PostgreSQL Credentials Exposed

**Detection Date:** February 4, 2026  
**Alert Source:** GitGuardian  
**Severity:** CRITICAL  
**Status:** REQUIRES IMMEDIATE ACTION

---

## EXPOSED CREDENTIALS

**Secret Type:** PostgreSQL URI  
**Repository:** 360watts/smart-solar-django-backend  
**File:** `.env.pg`  
**Pushed:** February 4, 2026, 07:34:00 UTC  

### Exposed URI (NOW REVOKED):
```
postgres://postgres.gradxxhofbryazulajfy:3K2okENJGWtk3qH6@aws-1-ap-south-1.pooler.supabase.com:6543/postgres?sslmode=require
```

**Details:**
- Host: aws-1-ap-south-1.pooler.supabase.com (Supabase)
- User: postgres.gradxxhofbryazulajfy
- Password: 3K2okENJGWtk3qH6 (COMPROMISED)
- Database: postgres
- Port: 6543 (pooler)

---

## IMMEDIATE ACTIONS TAKEN

✅ **1. Updated .gitignore**
   - Added `.env.*` pattern to prevent future env file commits
   - All environment files now excluded from git tracking

✅ **2. Created .env.example**
   - Template file for developers with NO credentials
   - Includes all required environment variables as placeholders
   - Safe to commit to repository

✅ **3. Documented Issue**
   - This security report for team reference
   - Clear remediation steps outlined below

---

## URGENT REMEDIATION STEPS

### 1. ⚠️ RESET DATABASE CREDENTIALS (DO THIS NOW)

**Contact Supabase immediately:**
1. Go to https://supabase.com/dashboard
2. Select your project
3. Navigate to Settings → Database → Password Reset
4. Generate a new password for `postgres` user
5. Update `.env` or deployment variables with the new password

**This revokes the exposed credentials and prevents unauthorized access.**

### 2. 🔍 AUDIT DATABASE ACTIVITY

Check Supabase audit logs for any suspicious activity:
1. Go to Settings → Audit Logs
2. Filter for logins/connections after February 4, 2026, 07:34:00 UTC
3. Check for any unauthorized queries or data access
4. Document any suspicious activity

### 3. 🧹 REMOVE FROM GIT HISTORY

**Option A: Using `git filter-branch` (entire history)**
```bash
cd smart-solar-django-backend
git filter-branch --tree-filter 'rm -f .env.pg' -- --all
git push origin --force --all
git push origin --force --tags
```

**Option B: Using BFG Repo-Cleaner (faster)**
```bash
bfg --delete-files .env.pg smart-solar-django-backend
cd smart-solar-django-backend
git reflog expire --expire=now --all
git gc --prune=now --aggressive
git push origin --force --all
```

**Note:** These commands rewrite git history. Notify all team members to re-clone the repository.

### 4. 📝 UPDATE DEPLOYMENT VARIABLES

Update ALL deployment environments with the new database credentials:

**Vercel (Frontend & Backend):**
1. Go to Project Settings → Environment Variables
2. Update `DATABASE_URL` with new credentials
3. Re-deploy the application

**Docker/Local Development:**
1. Update `.env` file with new credentials
2. Do NOT commit `.env` to git
3. Use `.env.example` as template reference

### 5. 🔐 ROTATE OTHER SECRETS

While addressing this incident, review and rotate:
- [ ] Django `SECRET_KEY`
- [ ] JWT signing keys
- [ ] Any API keys or tokens
- [ ] Database backup encryption keys

---

## PREVENTION MEASURES IMPLEMENTED

### 1. **Updated .gitignore**
```gitignore
# Environments
.env
.env.*           # ← Now catches .env.pg, .env.local, .env.test, etc.
.venv
env/
venv/
```

### 2. **Created .env.example**
- Safe template for developers
- Committed to repository as reference
- No actual credentials included

### 3. **Best Practices Documentation**

**For Developers:**
- NEVER commit `.env` or any `.env.*` files to git
- Use `.env.example` as a template
- Copy it to `.env` locally: `cp .env.example .env`
- Fill in your own credentials
- Run `git config core.hooksPath .githooks` (if using pre-commit hooks)

**For CI/CD:**
- Use GitHub Secrets / GitLab Variables for credentials
- Pass credentials as environment variables at runtime
- Never store secrets in code or commits

---

## RECOMMENDED MONITORING

### 1. **Enable GitGuardian**
- Set up continuous monitoring for future secrets
- Configure webhooks for immediate alerts
- Review detected secrets weekly

### 2. **Git Pre-commit Hook (Optional)**
Create `.githooks/pre-commit`:
```bash
#!/bin/bash
if git diff --cached | grep -i "password\|secret\|api.key\|postgres://"; then
    echo "ERROR: Potential credentials detected in commit!"
    exit 1
fi
```

### 3. **Code Scanning**
- Enable GitHub Security tab → Code scanning
- Use Trivy or similar tools in CI/CD
- Scan for exposed secrets before merge

---

## TIMELINE

| Date & Time | Event |
|---|---|
| 2026-02-04 07:34:00 UTC | `.env.pg` pushed to GitHub with exposed credentials |
| 2026-02-04 | GitGuardian alert received |
| 2026-02-04 | This incident report generated |
| **ACTION REQUIRED** | **Supabase credentials must be reset immediately** |

---

## CONTACT & FOLLOW-UP

**Action Items:**
- [ ] Reset Supabase database password
- [ ] Audit database activity logs
- [ ] Remove from git history (filter-branch or bfg)
- [ ] Update all deployment variables
- [ ] Notify team members to re-clone
- [ ] Rotate other secrets if needed
- [ ] Set up secrets monitoring

**Team Communication:**
Notify team members that they need to:
1. Re-clone the repository after history is rewritten
2. Use new database credentials in `.env`
3. Not commit sensitive files

---

## REFERENCES

- [Supabase Security Docs](https://supabase.com/docs/security)
- [Git Filter Branch](https://git-scm.com/docs/git-filter-branch)
- [BFG Repo-Cleaner](https://rtyley.github.io/bfg-repo-cleaner/)
- [OWASP Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)

---

**Report Generated:** 2026-02-04  
**Status:** REQUIRES IMMEDIATE ACTION
