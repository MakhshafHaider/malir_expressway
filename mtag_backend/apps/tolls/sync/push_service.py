"""
Push service: copies locally-created/updated records → master.

Tables pushed:
  - users        — new/updated users (operators, vehicle owners)
  - vehicles     — new registrations + status changes
  - tags         — tag assignments (vehicle_id) + status changes
  - accounts     — balance changes from offline exits
  - toll_trips   — uses updated_at so BOTH new entries AND exit updates reach master
  - transactions — new records only (immutable, use processed_at)

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


def push_users(local_cur, master_cur, since: datetime) -> int:
    """Push new/updated users (owners, operators) to master."""
    local_cur.execute("""
        SELECT id, password, last_login, is_superuser, uuid, full_name,
               cnic, phone, user_role, status, is_staff, created_at,
               updated_at, created_by_id, last_login_at
        FROM users WHERE updated_at > %s OR created_at > %s
    """, (since, since))
    rows = local_cur.fetchall()
    if not rows:
        return 0
    psycopg2.extras.execute_values(master_cur, """
        INSERT INTO users (id, password, last_login, is_superuser, uuid,
               full_name, cnic, phone, user_role, status, is_staff,
               created_at, updated_at, created_by_id, last_login_at)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            password    = EXCLUDED.password,
            status      = EXCLUDED.status,
            user_role   = EXCLUDED.user_role,
            updated_at  = EXCLUDED.updated_at
        WHERE users.updated_at < EXCLUDED.updated_at
    """, rows)
    return len(rows)


def push_vehicles(local_cur, master_cur, since: datetime) -> int:
    """Push new vehicle registrations and status changes to master."""
    local_cur.execute("""
        SELECT id, owner_id, plate_number, vehicle_type, status,
               registered_at, updated_at
        FROM vehicles WHERE updated_at > %s OR registered_at > %s
    """, (since, since))
    rows = local_cur.fetchall()
    if not rows:
        return 0
    psycopg2.extras.execute_values(master_cur, """
        INSERT INTO vehicles (id, owner_id, plate_number, vehicle_type,
               status, registered_at, updated_at)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            status       = EXCLUDED.status,
            plate_number = EXCLUDED.plate_number,
            updated_at   = EXCLUDED.updated_at
        WHERE vehicles.updated_at < EXCLUDED.updated_at
    """, rows)
    return len(rows)


def push_tags(local_cur, master_cur, since: datetime) -> int:
    """Push tag assignments (vehicle_id) and status changes to master."""
    local_cur.execute("""
        SELECT id, tag_serial, epc, vehicle_id, issued_at,
               expiry_date, status, last_scanned_at, updated_at
        FROM tags WHERE updated_at > %s
    """, (since,))
    rows = local_cur.fetchall()
    if not rows:
        return 0
    psycopg2.extras.execute_values(master_cur, """
        INSERT INTO tags (id, tag_serial, epc, vehicle_id, issued_at,
               expiry_date, status, last_scanned_at, updated_at)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            vehicle_id      = EXCLUDED.vehicle_id,
            status          = EXCLUDED.status,
            expiry_date     = EXCLUDED.expiry_date,
            last_scanned_at = EXCLUDED.last_scanned_at,
            updated_at      = EXCLUDED.updated_at
        WHERE tags.updated_at < EXCLUDED.updated_at
    """, rows)
    return len(rows)


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
                    ('users',        push_users),
                    ('vehicles',     push_vehicles),
                    ('tags',         push_tags),
                    ('accounts',     push_accounts),
                    ('toll_trips',   push_toll_trips),
                    ('transactions', push_transactions),
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
