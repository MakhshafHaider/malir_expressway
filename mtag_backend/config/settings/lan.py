"""
LAN / internal-network deployment settings.
Use this when the server is on a private LAN without HTTPS.
DJANGO_SETTINGS_MODULE=config.settings.lan
"""
from .base import *

DEBUG = False

# ALLOWED_HOSTS must be set in .env (comma-separated IPs/hostnames)
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS')

# CORS origins set from .env
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[])

# ── Security (LAN-safe — no SSL redirect since LAN is HTTP-only) ──────────────
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# SSL is NOT enabled on LAN — do not redirect or set HSTS
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
