"""
Gunicorn configuration for m-tag gate PC (LAN deployment).
Run: gunicorn -c gunicorn.conf.py config.wsgi:application
"""
import multiprocessing

# 1 worker is enough for a gate PC.
# Multiple workers cause sync agent + ANPR gate to start once per worker
# (duplicate WS connections, duplicate sync threads). Single worker avoids this.
workers = 1
worker_class = "gthread"
threads = 4

# Bind to all interfaces so other PCs on LAN can reach the API
bind = "0.0.0.0:8000"

# Timeouts
timeout = 60
keepalive = 5

# Logging
accesslog = "-"   # stdout
errorlog  = "-"   # stdout
loglevel  = "info"

# Reload on code changes (set False in production)
reload = False
