"""
Direct psycopg2 connection factories for sync agent.
These bypass Django ORM — one connection per server, always explicit.
"""
import logging
import psycopg2
from django.conf import settings

log = logging.getLogger('apps.tolls.sync')


def _get_conn(db_alias: str):
    cfg = settings.DATABASES[db_alias]
    opts = cfg.get('OPTIONS', {})
    return psycopg2.connect(
        dbname=cfg['NAME'],
        user=cfg['USER'],
        password=cfg['PASSWORD'],
        host=cfg['HOST'],
        port=cfg.get('PORT', 5432),
        connect_timeout=opts.get('connect_timeout', 3),
    )


def get_local_conn():
    """Always connects to localhost PostgreSQL."""
    return _get_conn('local_pg')


def get_master_conn():
    """Always connects to master PostgreSQL.
    Raises OperationalError if master is unreachable."""
    return _get_conn('master_pg')


def master_is_reachable() -> bool:
    try:
        conn = get_master_conn()
        conn.close()
        return True
    except psycopg2.OperationalError:
        return False
