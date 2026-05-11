"""
Pull service: copies master → local.

Tables pulled (master is authoritative):
  - plazas, toll_lanes, toll_rates, tags  — full refresh every cycle (no updated_at)
  - users, vehicles, accounts             — timestamp-based
  - toll_trips (active)                   — full refresh so exit gate finds entries
                                            from any plaza on the network

Strategy: ON CONFLICT DO UPDATE so local always mirrors master.
          accounts pull has a timestamp guard so an offline balance deduction
          on local is never overwritten by an older master value.
"""
import logging
from datetime import datetime, timezone

import psycopg2.extras

from apps.tolls.sync.connections import get_local_conn, get_master_conn

log = logging.getLogger('apps.tolls.sync.pull')


def _now():
    return datetime.now(timezone.utc)


def _get_last_pull(local_cur, table: str):
    local_cur.execute(
        "SELECT last_pull_at FROM sync_log WHERE table_name = %s",
        (table,)
    )
    row = local_cur.fetchone()
    if row and row[0]:
        return row[0]
    return datetime(2000, 1, 1, tzinfo=timezone.utc)


def _set_last_pull(local_cur, table: str, ts: datetime):
    local_cur.execute("""
        INSERT INTO sync_log (table_name, last_pull_at)
        VALUES (%s, %s)
        ON CONFLICT (table_name) DO UPDATE SET last_pull_at = EXCLUDED.last_pull_at
    """, (table, ts))


# ── Full-refresh tables (no timestamp columns) ────────────────────────────────

def pull_plazas(master_cur, local_cur) -> int:
    master_cur.execute(
        "SELECT id, name, code, latitude, longitude, is_active FROM plazas"
    )
    rows = master_cur.fetchall()
    if not rows:
        return 0
    psycopg2.extras.execute_values(local_cur, """
        INSERT INTO plazas (id, name, code, latitude, longitude, is_active)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            name      = EXCLUDED.name,
            code      = EXCLUDED.code,
            latitude  = EXCLUDED.latitude,
            longitude = EXCLUDED.longitude,
            is_active = EXCLUDED.is_active
    """, rows)
    return len(rows)


def pull_toll_lanes(master_cur, local_cur) -> int:
    master_cur.execute(
        "SELECT id, plaza_id, lane_number, is_active FROM toll_lanes"
    )
    rows = master_cur.fetchall()
    if not rows:
        return 0
    psycopg2.extras.execute_values(local_cur, """
        INSERT INTO toll_lanes (id, plaza_id, lane_number, is_active)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            is_active   = EXCLUDED.is_active,
            lane_number = EXCLUDED.lane_number
    """, rows)
    return len(rows)


def pull_toll_rates(master_cur, local_cur) -> int:
    master_cur.execute("""
        SELECT id, entry_plaza_id, exit_plaza_id, vehicle_type,
               rate, peak_multiplier, effective_from
        FROM toll_rates
    """)
    rows = master_cur.fetchall()
    if not rows:
        return 0
    psycopg2.extras.execute_values(local_cur, """
        INSERT INTO toll_rates (id, entry_plaza_id, exit_plaza_id,
               vehicle_type, rate, peak_multiplier, effective_from)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            rate             = EXCLUDED.rate,
            peak_multiplier  = EXCLUDED.peak_multiplier
    """, rows)
    return len(rows)


def pull_tags(master_cur, local_cur) -> int:
    """Full refresh — Tag model has no updated_at, so timestamp-based sync
    would miss status changes (suspend/reactivate). Table is small (<10k rows)."""
    master_cur.execute("""
        SELECT id, tag_serial, epc, vehicle_id, issued_at,
               expiry_date, status, last_scanned_at
        FROM tags
    """)
    rows = master_cur.fetchall()
    if not rows:
        return 0
    psycopg2.extras.execute_values(local_cur, """
        INSERT INTO tags (id, tag_serial, epc, vehicle_id, issued_at,
               expiry_date, status, last_scanned_at)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            status          = EXCLUDED.status,
            vehicle_id      = EXCLUDED.vehicle_id,
            last_scanned_at = EXCLUDED.last_scanned_at
    """, rows)
    return len(rows)


# ── Timestamp-tracked tables ──────────────────────────────────────────────────

def pull_users(master_cur, local_cur, since: datetime) -> int:
    master_cur.execute("""
        SELECT id, password, last_login, is_superuser, uuid, full_name,
               cnic, phone, user_role, status, is_staff, created_at,
               updated_at, created_by_id, last_login_at
        FROM users WHERE updated_at > %s OR created_at > %s
    """, (since, since))
    rows = master_cur.fetchall()
    if not rows:
        return 0
    psycopg2.extras.execute_values(local_cur, """
        INSERT INTO users (id, password, last_login, is_superuser, uuid,
               full_name, cnic, phone, user_role, status, is_staff,
               created_at, updated_at, created_by_id, last_login_at)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            password    = EXCLUDED.password,
            status      = EXCLUDED.status,
            user_role   = EXCLUDED.user_role,
            updated_at  = EXCLUDED.updated_at
    """, rows)
    return len(rows)


def pull_vehicles(master_cur, local_cur, since: datetime) -> int:
    master_cur.execute("""
        SELECT id, owner_id, plate_number, vehicle_type, status,
               registered_at, updated_at
        FROM vehicles WHERE updated_at > %s OR registered_at > %s
    """, (since, since))
    rows = master_cur.fetchall()
    if not rows:
        return 0
    psycopg2.extras.execute_values(local_cur, """
        INSERT INTO vehicles (id, owner_id, plate_number, vehicle_type,
               status, registered_at, updated_at)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            status       = EXCLUDED.status,
            plate_number = EXCLUDED.plate_number,
            updated_at   = EXCLUDED.updated_at
    """, rows)
    return len(rows)


def pull_accounts(master_cur, local_cur, since: datetime) -> int:
    """
    Timestamp guard on DO UPDATE: only update local balance if master's
    balance_updated_at is newer. This prevents a master pull from overwriting
    a balance that was already deducted locally during an offline exit.
    """
    master_cur.execute("""
        SELECT id, vehicle_id, user_id, balance, created_at, balance_updated_at
        FROM accounts
        WHERE balance_updated_at > %s OR created_at > %s
    """, (since, since))
    rows = master_cur.fetchall()
    if not rows:
        return 0
    psycopg2.extras.execute_values(local_cur, """
        INSERT INTO accounts (id, vehicle_id, user_id, balance,
               created_at, balance_updated_at)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            balance            = EXCLUDED.balance,
            balance_updated_at = EXCLUDED.balance_updated_at
        WHERE accounts.balance_updated_at < EXCLUDED.balance_updated_at
    """, rows)
    return len(rows)


def pull_active_trips(master_cur, local_cur) -> int:
    """Pull ALL active trips from master — full refresh, no timestamp filter.
    Exit gate at Plaza B needs the entry trip created at Plaza A."""
    master_cur.execute("""
        SELECT id, vehicle_id, tag_id, account_id, entry_plaza_id,
               entry_lane_id, entry_time, exit_plaza_id, exit_lane_id,
               exit_time, charge_amount, balance_before, balance_after,
               status, created_at, updated_at
        FROM toll_trips WHERE status = 'active'
    """)
    rows = master_cur.fetchall()
    if not rows:
        return 0
    psycopg2.extras.execute_values(local_cur, """
        INSERT INTO toll_trips (id, vehicle_id, tag_id, account_id,
               entry_plaza_id, entry_lane_id, entry_time,
               exit_plaza_id, exit_lane_id, exit_time,
               charge_amount, balance_before, balance_after,
               status, created_at, updated_at)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            status        = EXCLUDED.status,
            exit_plaza_id = EXCLUDED.exit_plaza_id,
            exit_lane_id  = EXCLUDED.exit_lane_id,
            exit_time     = EXCLUDED.exit_time,
            charge_amount = EXCLUDED.charge_amount,
            balance_after = EXCLUDED.balance_after,
            updated_at    = EXCLUDED.updated_at
    """, rows)
    return len(rows)


def run_pull() -> dict:
    """Pull all tables from master into local. Returns summary dict."""
    summary = {}
    try:
        master_conn = get_master_conn()
        local_conn  = get_local_conn()
    except Exception as exc:
        log.warning("[pull] Cannot connect: %s", exc)
        return {'error': str(exc)}

    try:
        with master_conn, local_conn:
            with master_conn.cursor() as mc, local_conn.cursor() as lc:
                # Full-refresh tables (no timestamp columns)
                summary['plazas']     = pull_plazas(mc, lc)
                summary['toll_lanes'] = pull_toll_lanes(mc, lc)
                summary['toll_rates'] = pull_toll_rates(mc, lc)
                summary['tags']       = pull_tags(mc, lc)

                # Timestamp-tracked tables
                for table, fn in [
                    ('users',    pull_users),
                    ('vehicles', pull_vehicles),
                    ('accounts', pull_accounts),
                ]:
                    since = _get_last_pull(lc, table)
                    count = fn(mc, lc, since)
                    if count:
                        _set_last_pull(lc, table, _now())
                    summary[table] = count

                # Active trips — always full refresh
                summary['active_trips'] = pull_active_trips(mc, lc)

        log.info("[pull] done — %s", summary)
    except Exception as exc:
        log.error("[pull] error: %s", exc)
        summary['error'] = str(exc)
    finally:
        master_conn.close()
        local_conn.close()

    return summary
