import os
import sys
from pathlib import Path

# Add the project directory to the Python path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Set the Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localapi.settings')

# Note: django.setup() is called in api/index.py for serverless functions
# Do not call setup here as it causes reentrant errors during app loading
