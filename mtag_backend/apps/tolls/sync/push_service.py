"""
Push service: copies locally-created/updated records → master.

Tables pushed:
  - toll_trips   — uses updated_at so BOTH new entries AND exit updates reach master
  - transactions — new records only (immutable, use processed_at)
  - accounts     — balance changes from offline exits

Key design for toll_trips:
  Entry gate creates a new trip (updated_at advances) → pushed as INSERT.
  Exit gate updates that trip (updated_at advances again) → pushed as UPDATE.
  ON CONFLICT DO UPDATE with timestamp guard prevents stale overwrites.
"""
import logging
from datetime import datetime, timezone

import psycopg2.extras

from apps.tolls.sync.connections import get_local_conn, get_master_conn

log = logging.getLogger('apps.tolls.sync.push')


def _now():
    return datetime.now(timezone.utc)


def _get_last_push(local_cur, table: str):
    local_cur.execute(
        "SELECT last_push_at FROM sync_log WHERE table_name = %s",
        (f'push_{table}',)
    )
    row = local_cur.fetchone()
    if row and row[0]:
        return row[0]
    return datetime(2000, 1, 1, tzinfo=timezone.utc)


def _set_last_push(local_cur, table: str, ts: datetime):
    local_cur.execute("""
        INSERT INTO sync_log (table_name, last_push_at)
        VALUES (%s, %s)
        ON CONFLICT (table_name) DO UPDATE SET last_push_at = EXCLUDED.last_push_at
    """, (f'push_{table}', ts))


def push_toll_trips(local_cur, master_cur, since: datetime) -> int:
    """
    Push trips where updated_at > since.
    Catches new entry trips (just created) AND completed exit trips
    (updated_at advanced when exit closed the trip).
    """
    local_cur.execute("""
        SELECT id, vehicle_id, tag_id, account_id, entry_plaza_id,
               entry_lane_id, entry_time, exit_plaza_id, exit_lane_id,
               exit_time, charge_amount, balance_before, balance_after,
               status, created_at, updated_at
        FROM toll_trips WHERE updated_at > %s
    """, (since,))
    rows = local_cur.fetchall()
    if not rows:
        return 0
    psycopg2.extras.execute_values(master_cur, """
        INSERT INTO toll_trips (id, vehicle_id, tag_id, account_id,
               entry_plaza_id, entry_lane_id, entry_time,
               exit_plaza_id, exit_lane_id, exit_time,
               charge_amount, balance_before, balance_after,
               status, created_at, updated_at)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            status         = EXCLUDED.status,
            exit_plaza_id  = EXCLUDED.exit_plaza_id,
            exit_lane_id   = EXCLUDED.exit_lane_id,
            exit_time      = EXCLUDED.exit_time,
            charge_amount  = EXCLUDED.charge_amount,
            balance_before = EXCLUDED.balance_before,
            balance_after  = EXCLUDED.balance_after,
            updated_at     = EXCLUDED.updated_at
        WHERE toll_trips.updated_at < EXCLUDED.updated_at
    """, rows)
    return len(rows)


def push_transactions(local_cur, master_cur, since: datetime) -> int:
    """Transactions are immutable — push new ones only via processed_at."""
    local_cur.execute("""
        SELECT id, account_id, toll_trip_id, toll_lane_id, tag_serial, amount,
               transaction_type, balance_before, balance_after, status,
               source, idempotency_key, reference_id, processed_at
        FROM transactions WHERE processed_at > %s
    """, (since,))
    rows = local_cur.fetchall()
    if not rows:
        return 0
    psycopg2.extras.execute_values(master_cur, """
        INSERT INTO transactions (id, account_id, toll_trip_id,
               toll_lane_id, tag_serial, amount,
               transaction_type, balance_before, balance_after, status,
               source, idempotency_key, reference_id, processed_at)
        VALUES %s
        ON CONFLICT (id) DO NOTHING
    """, rows)
    return len(rows)


def push_accounts(local_cur, master_cur, since: datetime) -> int:
    """Push account balance changes to master.
    Timestamp guard: master only accepts update if local's balance_updated_at
    is newer — prevents stale local data from overwriting fresher master data."""
    local_cur.execute("""
        SELECT id, vehicle_id, user_id, balance, created_at, balance_updated_at
        FROM accounts WHERE balance_updated_at > %s
    """, (since,))
    rows = local_cur.fetchall()
    if not rows:
        return 0
    psycopg2.extras.execute_values(master_cur, """
        INSERT INTO accounts (id, vehicle_id, user_id, balance,
               created_at, balance_updated_at)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            balance            = EXCLUDED.balance,
            balance_updated_at = EXCLUDED.balance_updated_at
        WHERE accounts.balance_updated_at < EXCLUDED.balance_updated_at
    """, rows)
    return len(rows)


def run_push() -> dict:
    """Push locally-modified records to master. Returns summary dict."""
    summary = {}
    try:
        local_conn  = get_local_conn()
        master_conn = get_master_conn()
    except Exception as exc:
        log.warning("[push] Cannot connect to master: %s", exc)
        return {'error': str(exc)}

    try:
        with local_conn, master_conn:
            with local_conn.cursor() as lc, master_conn.cursor() as mc:
                for table, fn in [
                    ('toll_trips',   push_toll_trips),
                    ('transactions', push_transactions),
                    ('accounts',     push_accounts),
                ]:
                    since = _get_last_push(lc, table)
                    count = fn(lc, mc, since)
                    if count:
                        _set_last_push(lc, table, _now())
                    summary[table] = count

        log.info("[push] done — %s", summary)
    except Exception as exc:
        log.error("[push] error: %s", exc)
        summary['error'] = str(exc)
    finally:
        local_conn.close()
        master_conn.close()

    return summary
