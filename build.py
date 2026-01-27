#!/usr/bin/env python
import os
import sys
import subprocess
from pathlib import Path


# No-op build script: migrations and collectstatic must be run outside Vercel build step.
print("Vercel build: skipping migrations and collectstatic. Run these locally or in CI/CD.")
