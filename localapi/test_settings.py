"""
Django test settings for running tests without requiring local PostgreSQL
Uses SQLite in-memory database for fast, isolated testing
"""

import os
import tempfile
from localapi.settings import *

# Override database to use SQLite for testing
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',  # In-memory database for tests
    }
}

# Disable migrations for faster test setup
class DisableMigrations:
    def __contains__(self, item):
        return True
    
    def __getitem__(self, item):
        return None

MIGRATION_MODULES = DisableMigrations()

# Use simple password hasher for faster tests
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# Disable debug toolbar and other non-essential middleware for tests
MIDDLEWARE = [m for m in MIDDLEWARE if 'toolbar' not in m]

# Use LocMemCache for tests (supports atomic increment for rate limiting)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'test-cache',
    }
}

# Disable system checks for django-ratelimit in tests (locmem cache works fine for testing)
SILENCED_SYSTEM_CHECKS = [
    'django_ratelimit.E003',
    'django_ratelimit.W001',
]
