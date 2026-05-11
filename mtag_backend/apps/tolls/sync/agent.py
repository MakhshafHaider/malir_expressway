"""
Sync agent — runs pull + push every 30 seconds in a background thread.
Call start() once at Django startup (AppConfig.ready).
"""
import logging
import threading
import time

from apps.tolls.sync.pull_service import run_pull
from apps.tolls.sync.push_service import run_push

log = logging.getLogger('apps.tolls.sync.agent')

SYNC_INTERVAL = 30  # seconds
_started = False
_lock    = threading.Lock()


def _loop():
    log.info("[sync] Agent started — interval=%ds", SYNC_INTERVAL)
    while True:
        try:
            pull_result = run_pull()
            push_result = run_push()
            if pull_result.get('error') or push_result.get('error'):
                log.warning("[sync] pull=%s push=%s", pull_result, push_result)
            else:
                log.debug("[sync] pull=%s push=%s", pull_result, push_result)
        except Exception as exc:
            log.error("[sync] Unexpected error: %s", exc)
        time.sleep(SYNC_INTERVAL)


def start():
    """Start the sync agent background thread. Safe to call multiple times."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    t = threading.Thread(target=_loop, name='pg-sync-agent', daemon=True)
    t.start()
    log.info("[sync] Background thread started")
