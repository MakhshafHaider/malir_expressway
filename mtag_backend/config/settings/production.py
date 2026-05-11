from .base import *

# ─── Safety guards ────────────────────────────────────────────────────────────
if SECRET_KEY == 'your-secret-key-here':
    raise ValueError(
        "SECRET_KEY must be set to a cryptographically secure random value. "
        "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(50))\""
    )

# ALLOWED_HOSTS is required in production — no default fallback
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS')

# CORS origins must be explicitly set — no wildcard allowed with credentials
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS')

# ─── Security ─────────────────────────────────────────────────────────────────
DEBUG = False
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
