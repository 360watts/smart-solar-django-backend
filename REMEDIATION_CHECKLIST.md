# Security Remediation Checklist

## CRITICAL: PostgreSQL Credentials Exposed

**Alert:** GitGuardian detected PostgreSQL URI with credentials in `.env.pg`  
**Status:** REQUIRES IMMEDIATE ACTION  
**Priority:** 🔴 CRITICAL

---

## Exposed Credentials Summary

| Detail | Value |
|---|---|
| File | `.env.pg` |
| Host | aws-1-ap-south-1.pooler.supabase.com (Supabase) |
| Username | postgres.gradxxhofbryazulajfy |
| Password | 3K2okENJGWtk3qH6 |
| Database | postgres |
| Port | 6543 |
| Status | **MUST BE REVOKED** |

---

## IMMEDIATE ACTION ITEMS

### 🔴 PRIORITY 1: Reset Database Credentials (DO THIS NOW!)

**Supabase Password Reset:**
1. Go to https://supabase.com/dashboard
2. Select your project
3. Click **Settings** → **Database** → **Password Reset**
4. Generate a new strong password
5. Copy the new password
6. Update all `.env` files and deployment variables with the new password

**Timeline:** Complete within 1 hour

**Verification:**
```bash
# Test new connection
psql postgresql://postgres.newpassword@aws-1-ap-south-1.pooler.supabase.com:6543/postgres
```

---

### 🟠 PRIORITY 2: Remove from Git History

**Option A: Using git filter-branch (Safest)**
```bash
cd smart-solar-django-backend

# Remove .env.pg from entire history
git filter-branch --tree-filter 'rm -f .env.pg' -- --all

# Force push to all branches
git push origin --force --all
git push origin --force --tags

# Clean up
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

**Option B: Using BFG Repo-Cleaner (Faster)**
```bash
# Install: brew install bfg (macOS) or download from GitHub

bfg --delete-files .env.pg smart-solar-django-backend
cd smart-solar-django-backend
git reflog expire --expire=now --all
git gc --prune=now --aggressive
git push origin --force --all
```

**Timeline:** Complete within 2 hours  
**Note:** All team members must re-clone after history is rewritten

---

### 🟡 PRIORITY 3: Audit & Update

**Supabase Audit Log:**
1. Go to https://supabase.com/dashboard → Settings → Audit Logs
2. Filter for activity after February 4, 2026, 07:34:00 UTC
3. Check for unauthorized:
   - Logins
   - Queries
   - Data modifications
   - User additions/deletions
4. Document any suspicious activity
5. Contact Supabase support if suspicious activity found

**Update Deployment Variables:**

**Vercel Backend:**
1. Go to Vercel Dashboard → smart-solar-django-backend
2. Settings → Environment Variables
3. Update `DATABASE_URL` with new credentials
4. Click "Save"
5. Redeploy

**Vercel Frontend:**
1. Go to Vercel Dashboard → smart-solar-react-frontend
2. Settings → Environment Variables
3. Verify `DATABASE_URL` is NOT stored there
4. Redeploy if any changes

**Docker/Local:**
1. Update `.env` file with new credentials
2. Restart services: `docker-compose restart`

**Timeline:** Complete within 2 hours

---

### 🟢 PRIORITY 4: Prevention & Monitoring

**Already Completed:**
✅ Updated `.gitignore` to include `.env.*`  
✅ Created `.env.example` template  
✅ Created `SECURITY_INCIDENT.md` documentation  
✅ Created `ENVIRONMENT_SETUP.md` guide  

**Still To Do:**
- [ ] Enable GitGuardian continuous monitoring
- [ ] Set up GitHub branch protection (require reviews)
- [ ] Consider pre-commit hooks for secrets detection

---

## Team Communication Template

Share this with your team:

```
🚨 SECURITY ALERT 🚨

A PostgreSQL password was accidentally committed to GitHub and detected by GitGuardian.

The exposed credentials have been REVOKED. Here's what you need to do:

1. **Database Password:** Has been reset at Supabase
   - Do NOT use old credentials
   - Check your email for new temporary password
   - Update your local `.env` file

2. **Sync Changes:** Pull the latest code
   ```bash
   cd smart-solar-django-backend
   git pull origin main --force
   ```

3. **Update .env:** 
   ```bash
   cp .env.example .env
   # Update with new database credentials
   ```

4. **Re-clone if needed:**
   - Git history has been rewritten
   - If you encounter issues, delete and re-clone:
   ```bash
   rm -rf smart-solar-django-backend
   git clone https://github.com/360watts/smart-solar-django-backend.git
   ```

5. **Restart Services:**
   ```bash
   docker-compose restart  # or restart your local server
   ```

Questions? See SECURITY_INCIDENT.md or ENVIRONMENT_SETUP.md

Thanks for your attention to security!
```

---

## Verification Checklist

After completing all items above:

- [ ] **Database:** New credentials are working
  ```bash
  psql postgresql://new_user:new_pass@host:6543/postgres -c "SELECT 1"
  ```

- [ ] **Git:** `.env.pg` is removed from history
  ```bash
  git log --all --full-history -- .env.pg
  # Should return nothing or only old commits
  ```

- [ ] **GitHub:** Repository shows rewritten history
  - Visit: https://github.com/360watts/smart-solar-django-backend/commits/main
  - Verify no `.env.pg` in recent commits

- [ ] **Vercel:** Redeployed with new credentials
  - Check: Vercel Dashboard → Deployments
  - Verify latest deployment status is "Ready"

- [ ] **Team:** All members notified
  - Email sent ✓
  - Slack/Discord message sent ✓
  - Standup meeting discussed ✓

- [ ] **Monitoring:** GitGuardian enabled
  - Dashboard activated
  - Webhooks configured
  - Alert notifications setup

---

## Ongoing Security Measures

### Weekly
- [ ] Review GitGuardian alerts (if any)
- [ ] Check for new GitHub security advisories

### Monthly
- [ ] Rotate sensitive credentials (passwords, tokens)
- [ ] Audit team member repository access
- [ ] Review git audit logs

### Quarterly
- [ ] Security training for developers
- [ ] Infrastructure security review
- [ ] Dependencies vulnerability scan

---

## Reference Documents

Created in this incident:
- [SECURITY_INCIDENT.md](./SECURITY_INCIDENT.md) - Full incident details
- [ENVIRONMENT_SETUP.md](./ENVIRONMENT_SETUP.md) - Developer guide
- [.env.example](./.env.example) - Safe template for credentials
- [.gitignore](./.gitignore) - Updated to prevent future exposure

---

## Support & Questions

If you encounter issues:

1. **Check the guides:**
   - SECURITY_INCIDENT.md → Full remediation steps
   - ENVIRONMENT_SETUP.md → Developer setup help

2. **Common issues:**
   - Database connection failed → Check DATABASE_URL format
   - Git history issues → Run `git reflog expire && git gc`
   - Deployment failed → Verify environment variables in Vercel

3. **Contact:**
   - Supabase Support: https://supabase.com/support
   - GitHub Security: https://github.com/security
   - Team Lead: [contact information]

---

**Status:** 🔴 CRITICAL - ACTION REQUIRED  
**Created:** 2026-02-04  
**Last Updated:** 2026-02-04  
**Next Review:** 2026-02-05
