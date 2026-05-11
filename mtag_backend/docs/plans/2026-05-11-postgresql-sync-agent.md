# PostgreSQL Sync Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SQLite offline cache with a PostgreSQL-based bidirectional sync agent that keeps local PC in sync with master DB every 30 seconds, enabling multi-plaza toll operations even when master is temporarily unreachable.

**Architecture:** Each gate PC runs a sync agent (background thread) that pulls reference data + all active trips from master into local PostgreSQL every 30 seconds, and pushes any locally-created trips/transactions back to master. ExitService checks local DB first for active trips, falling back to master — this handles the case where entry was at another plaza and not yet pulled locally. Balance deduction always runs on whichever DB is currently reachable via the existing multi-host `default` connection.

**Tech Stack:** Django, psycopg2 (direct connections for sync — no ORM router complexity), PostgreSQL 14+ on both master and local.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `config/settings/base.py` | Modify | Add `local_pg` and `master_pg` explicit DB configs |
| `apps/tolls/sync/__init__.py` | Create | Package marker |
| `apps/tolls/sync/connections.py` | Create | Direct psycopg2 connection helpers for local/master |
| `apps/tolls/sync/pull_service.py` | Create | Pull master → local (reference data + active trips) |
| `apps/tolls/sync/push_service.py` | Create | Push local → master (locally created trips/transactions) |
| `apps/tolls/sync/agent.py` | Create | Orchestrator — runs pull+push every 30s |
| `apps/tolls/management/commands/run_sync_agent.py` | Create | Django management command for standalone run |
| `apps/tolls/services.py` | Modify | ExitService: local-first active trip lookup |
| `apps/tolls/apps.py` | Modify | Auto-start sync agent in ready() |
| `apps/tolls/migrations/0006_sync_log.py` | Create | SyncLog table to track last sync times |
| `apps/tolls/models.py` | Modify | Add SyncLog model |

---

## Task 1: Add Explicit DB Connections to Settings

**Files:**
- Modify: `config/settings/base.py`

- [ ] **Step 1: Add local_pg and master_pg to DATABASES**

Open `config/settings/base.py`. After the existing `DATABASES` block, add:

```python
# Explicit single-host connections used by sync agent.
# These bypass the multi-host failover — each always targets one server.
_local_options  = {'connect_timeout': 3}
_master_options = {'connect_timeout': 3}

DATABASES['local_pg'] = {
    'ENGINE':   'django.db.backends.postgresql',
    'NAME':     env('DB_NAME',     default='tag_db'),
    'USER':     env('DB_USER',     default='postgres'),
    'PASSWORD': env('DB_PASSWORD', default='postgres'),
    'HOST':     'localhost',
    'PORT':     _db_port,
    'OPTIONS':  _local_options,
}

DATABASES['master_pg'] = {
    'ENGINE':   'django.db.backends.postgresql',
    'NAME':     env('DB_NAME',     default='tag_db'),
    'USER':     env('DB_USER',     default='postgres'),
    'PASSWORD': env('DB_PASSWORD', default='postgres'),
    'HOST':     _db_primary,
    'PORT':     _db_port,
    'OPTIONS':  _master_options,
}
```

- [ ] **Step 2: Verify settings load without error**

```bash
python manage.py check
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 3: Commit**

```bash
git add config/settings/base.py
git commit -m "feat: add explicit local_pg and master_pg DB configs for sync agent"
```

---

## Task 2: Model Changes + Migration

**Files:**
- Modify: `apps/tolls/models.py`
- Create: migration via `makemigrations`

**Two changes in this task:**
1. Add `updated_at` to `TollTrip` — without it, exit updates can never be pushed to master (exit changes status, charge_amount, exit_plaza — but `created_at` never changes after creation, so push can't detect the update).
2. Add `SyncLog` model.

- [ ] **Step 1: Add `updated_at` to TollTrip in models.py**

In `apps/tolls/models.py`, find the `TollTrip` class and add `updated_at` after `created_at`:

```python
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)   # ← add this line
```

- [ ] **Step 2: Add `updated_at` index to TollTrip.Meta.indexes**

In the same `TollTrip.Meta` class, add the index so sync queries are fast:

```python
    class Meta:
        db_table = 'toll_trips'
        indexes = [
            models.Index(fields=['vehicle', 'status']),
            models.Index(fields=['entry_time']),
            models.Index(fields=['updated_at']),   # ← add this
        ]
```

- [ ] **Step 3: Add SyncLog model at the bottom of models.py**

```python
class SyncLog(models.Model):
    """Tracks last successful sync timestamp per table per direction."""
    table_name   = models.CharField(max_length=60, unique=True)
    last_pull_at = models.DateTimeField(null=True, blank=True)
    last_push_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'sync_log'

    def __str__(self):
        return self.table_name
```

- [ ] **Step 4: Generate migration**

```bash
python manage.py makemigrations tolls --name sync_log_and_trip_updated_at
```

Expected output: `Migrations for 'tolls': apps/tolls/migrations/0006_sync_log_and_trip_updated_at.py`

- [ ] **Step 5: Run migration on local DB**

```bash
python manage.py migrate
```

Expected: `Applying tolls.0006_sync_log_and_trip_updated_at... OK`

- [ ] **Step 6: Run migration on master DB**

```bash
python manage.py migrate --database=master_pg
```

Expected: `Applying tolls.0006_sync_log_and_trip_updated_at... OK`

- [ ] **Step 7: Commit**

```bash
git add apps/tolls/models.py apps/tolls/migrations/
git commit -m "feat: add TollTrip.updated_at and SyncLog model"
```

---

## Task 3: Connection Helpers

**Files:**
- Create: `apps/tolls/sync/__init__.py`
- Create: `apps/tolls/sync/connections.py`

- [ ] **Step 1: Create package**

```bash
touch "apps/tolls/sync/__init__.py"
```

- [ ] **Step 2: Create connections.py**

```python
# apps/tolls/sync/connections.py
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
    """Always connects to master PostgreSQL (192.168.78.200).
    Raises OperationalError if master is unreachable."""
    return _get_conn('master_pg')


def master_is_reachable() -> bool:
    try:
        conn = get_master_conn()
        conn.close()
        return True
    except psycopg2.OperationalError:
        return False
```

- [ ] **Step 3: Verify import works**

```bash
python manage.py shell -c "
from apps.tolls.sync.connections import master_is_reachable
print('Master reachable:', master_is_reachable())
"
```

Expected: `Master reachable: True` (or False if master is down — both are valid)

- [ ] **Step 4: Commit**

```bash
git add apps/tolls/sync/
git commit -m "feat: add sync package with psycopg2 connection helpers"
```

---

## Task 4: Pull Service (Master → Local)

**Files:**
- Create: `apps/tolls/sync/pull_service.py`

**What gets pulled:** All reference data (plazas, lanes, rates, users, vehicles, tags, accounts) + ALL active trips from master. Active trips from other plazas let exit gate find entries it didn't create locally.

- [ ] **Step 1: Create pull_service.py**

```python
# apps/tolls/sync/pull_service.py
"""
Pull service: copies master → local.

Tables pulled (master is authoritative):
  - plazas, toll_lanes, toll_rates  — full refresh every cycle (no timestamps in these tables)
  - users, vehicles, tags           — timestamp-based (updated_at)
  - accounts                        — timestamp-based (balance_updated_at); guarded so
                                      local offline deductions are NEVER overwritten by
                                      older master values
  - toll_trips (active)             — full refresh so exit gate finds entries from any plaza
  - toll_trips (recent updated)     — timestamp-based (updated_at) for completed trips

Strategy: ON CONFLICT DO UPDATE so local always mirrors master.
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


# ── Static tables (no timestamp columns — full refresh every cycle) ────────────

def pull_plazas(master_cur, local_cur) -> int:
    """Full refresh — plazas rarely change, table is tiny (< 20 rows)."""
    master_cur.execute("""
        SELECT id, name, code, latitude, longitude, is_active FROM plazas
    """)
    rows = master_cur.fetchall()
    if not rows:
        return 0
    psycopg2.extras.execute_values(local_cur, """
        INSERT INTO plazas (id, name, code, latitude, longitude, is_active)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name, code = EXCLUDED.code,
            latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude,
            is_active = EXCLUDED.is_active
    """, rows)
    return len(rows)


def pull_toll_lanes(master_cur, local_cur) -> int:
    """Full refresh — lanes rarely change."""
    master_cur.execute("""
        SELECT id, plaza_id, lane_number, is_active FROM toll_lanes
    """)
    rows = master_cur.fetchall()
    if not rows:
        return 0
    psycopg2.extras.execute_values(local_cur, """
        INSERT INTO toll_lanes (id, plaza_id, lane_number, is_active)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            is_active = EXCLUDED.is_active,
            lane_number = EXCLUDED.lane_number
    """, rows)
    return len(rows)


def pull_toll_rates(master_cur, local_cur) -> int:
    """Full refresh — rates change only when admin updates them."""
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
            rate = EXCLUDED.rate,
            peak_multiplier = EXCLUDED.peak_multiplier
    """, rows)
    return len(rows)


# ── Timestamp-tracked tables ───────────────────────────────────────────────────

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
            password = EXCLUDED.password, status = EXCLUDED.status,
            user_role = EXCLUDED.user_role, updated_at = EXCLUDED.updated_at
    """, rows)
    return len(rows)


def pull_vehicles(master_cur, local_cur, since: datetime) -> int:
    master_cur.execute("""
        SELECT id, owner_id, plate_number, vehicle_type, status,
               registered_at, updated_at
        FROM vehicles WHERE updated_at > %s OR created_at > %s
    """, (since, since))
    rows = master_cur.fetchall()
    if not rows:
        return 0
    psycopg2.extras.execute_values(local_cur, """
        INSERT INTO vehicles (id, owner_id, plate_number, vehicle_type,
               status, registered_at, updated_at)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            status = EXCLUDED.status,
            plate_number = EXCLUDED.plate_number,
            updated_at = EXCLUDED.updated_at
    """, rows)
    return len(rows)


def pull_tags(master_cur, local_cur) -> int:
    """
    Full refresh — Tag model has no updated_at column, so timestamp-based
    sync can't detect status changes (suspend/reactivate). Full refresh
    is safe: max ~10,000 rows on a busy expressway, trivial query time.
    """
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


def pull_accounts(master_cur, local_cur, since: datetime) -> int:
    """
    IMPORTANT — timestamp guard on balance:
    Account column is balance_updated_at (not updated_at).
    The DO UPDATE only runs when master's timestamp is NEWER than local.
    This prevents a master pull from overwriting a balance that was already
    deducted locally (offline exit) — which would give the vehicle a free toll.
    """
    master_cur.execute("""
        SELECT id, user_id, vehicle_id, balance, created_at, balance_updated_at
        FROM accounts
        WHERE balance_updated_at > %s OR created_at > %s
    """, (since, since))
    rows = master_cur.fetchall()
    if not rows:
        return 0
    psycopg2.extras.execute_values(local_cur, """
        INSERT INTO accounts (id, user_id, vehicle_id, balance,
               created_at, balance_updated_at)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            balance             = EXCLUDED.balance,
            balance_updated_at  = EXCLUDED.balance_updated_at
        WHERE accounts.balance_updated_at < EXCLUDED.balance_updated_at
    """, rows)
    return len(rows)


def pull_active_trips(master_cur, local_cur) -> int:
    """
    Pull ALL active trips from master — full refresh, no timestamp filter.
    This is the key for multi-plaza: exit gate needs entry trips from other plazas.
    Now includes updated_at so the push service can track exit updates.
    """
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
                # Static/no-timestamp tables — full refresh every cycle
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
```

- [ ] **Step 2: Test pull manually**

```bash
python manage.py shell -c "
from apps.tolls.sync.pull_service import run_pull
result = run_pull()
print(result)
"
```

Expected: `{'plazas': N, 'toll_lanes': N, ..., 'active_trips': N}`

- [ ] **Step 3: Commit**

```bash
git add apps/tolls/sync/pull_service.py
git commit -m "feat: add pull service (master to local sync)"
```

---

## Task 5: Push Service (Local → Master)

**Files:**
- Create: `apps/tolls/sync/push_service.py`

**What gets pushed:** Only records created locally (trips/transactions that happened while master was down or that this gate PC created). UUID keys mean ON CONFLICT DO NOTHING is safe — no duplicates.

- [ ] **Step 1: Create push_service.py**

```python
# apps/tolls/sync/push_service.py
"""
Push service: copies locally-created/updated records → master.

Tables pushed:
  - toll_trips   — both new entries AND exit updates (uses updated_at)
  - transactions — new records only (immutable after creation, processed_at)
  - accounts     — balance changes from offline exits

Key design:
  toll_trips uses updated_at > last_push_at with ON CONFLICT DO UPDATE.
  This handles two cases:
    1. Entry created locally (new row) → INSERT into master
    2. Exit updated locally (same row, updated_at advanced) → UPDATE on master
  Without updated_at tracking, exit updates would NEVER reach master.

  accounts push uses ON CONFLICT DO UPDATE with timestamp guard so master
  only accepts the local balance if local is newer (offline deduction).
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
    Push all trips where updated_at > since.
    This catches BOTH new entry trips (created_at advanced) and
    completed exit trips (updated_at advanced when exit closes the trip).
    ON CONFLICT DO UPDATE so exit fields are written to master even if
    the entry was already pushed in a previous cycle.
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
            status        = EXCLUDED.status,
            exit_plaza_id = EXCLUDED.exit_plaza_id,
            exit_lane_id  = EXCLUDED.exit_lane_id,
            exit_time     = EXCLUDED.exit_time,
            charge_amount = EXCLUDED.charge_amount,
            balance_before = EXCLUDED.balance_before,
            balance_after = EXCLUDED.balance_after,
            updated_at    = EXCLUDED.updated_at
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
    """
    Push account balance changes to master.
    Only runs when an offline exit deducted balance locally.
    Timestamp guard: master only accepts update if local is newer.
    """
    local_cur.execute("""
        SELECT id, user_id, vehicle_id, balance, created_at, balance_updated_at
        FROM accounts WHERE balance_updated_at > %s
    """, (since,))
    rows = local_cur.fetchall()
    if not rows:
        return 0
    psycopg2.extras.execute_values(master_cur, """
        INSERT INTO accounts (id, user_id, vehicle_id, balance,
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
        log.warning("[push] Cannot connect: %s", exc)
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
```

- [ ] **Step 2: Test push manually**

```bash
python manage.py shell -c "
from apps.tolls.sync.push_service import run_push
result = run_push()
print(result)
"
```

Expected: `{'toll_trips': N, 'transactions': N}` (0 if nothing new locally)

- [ ] **Step 3: Commit**

```bash
git add apps/tolls/sync/push_service.py
git commit -m "feat: add push service (local to master sync)"
```

---

## Task 6: Sync Agent Orchestrator

**Files:**
- Create: `apps/tolls/sync/agent.py`
- Create: `apps/tolls/management/commands/run_sync_agent.py`

- [ ] **Step 1: Create agent.py**

```python
# apps/tolls/sync/agent.py
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

SYNC_INTERVAL = 30   # seconds
_started = False
_lock    = threading.Lock()


def _loop():
    log.info("[sync] Agent started — interval=%ds", SYNC_INTERVAL)
    while True:
        try:
            pull_result = run_pull()
            push_result = run_push()
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
```

- [ ] **Step 2: Create run_sync_agent management command**

```python
# apps/tolls/management/commands/run_sync_agent.py
"""
Standalone sync agent — runs pull+push in foreground (no Django server needed).

Usage:
    python manage.py run_sync_agent
    python manage.py run_sync_agent --interval 60
"""
import time
import logging
from django.core.management.base import BaseCommand
from apps.tolls.sync.pull_service import run_pull
from apps.tolls.sync.push_service import run_push

log = logging.getLogger('apps.tolls.sync.agent')


class Command(BaseCommand):
    help = "Run PostgreSQL sync agent (pull master→local, push local→master)"

    def add_arguments(self, parser):
        parser.add_argument('--interval', type=int, default=30,
                            help='Sync interval in seconds (default: 30)')
        parser.add_argument('--once', action='store_true',
                            help='Run once and exit (useful for testing)')

    def handle(self, *args, **options):
        interval = options['interval']
        once     = options['once']

        self.stdout.write(f"[sync] Starting — interval={interval}s")

        while True:
            pull = run_pull()
            push = run_push()
            self.stdout.write(f"[sync] pull={pull}  push={push}")

            if once:
                break
            time.sleep(interval)
```

- [ ] **Step 3: Test standalone command**

```bash
python manage.py run_sync_agent --once
```

Expected output:
```
[sync] Starting — interval=30s
[sync] pull={'plazas': 0, 'toll_lanes': 0, ...}  push={'toll_trips': 0, 'transactions': 0}
```

- [ ] **Step 4: Commit**

```bash
git add apps/tolls/sync/agent.py apps/tolls/management/commands/run_sync_agent.py
git commit -m "feat: add sync agent orchestrator and management command"
```

---

## Task 7: ExitService — Local First Lookup

**Files:**
- Modify: `apps/tolls/services.py`

**Problem being solved:** Vehicle entered at Plaza A → trip saved in Plaza A's local DB → pushed to master → pulled to Plaza B's local DB. Exit at Plaza B needs to find this trip. Current ExitService only queries `default` (multi-host). We add: check local first, then master.

- [ ] **Step 1: Find ExitService.process_exit in services.py**

Read lines 135+ of `apps/tolls/services.py` to see the current ExitService.

- [ ] **Step 2: Add local-first trip lookup helper**

Add this function just before the `ExitService` class in `apps/tolls/services.py`:

```python
def _find_active_trip(vehicle):
    """
    Find active trip for vehicle.

    Lookup order:
      1. Local DB (default connection) — fast, covers 99% of cases.
         The sync agent pulls all active trips from master every 30s,
         so a vehicle that entered at another plaza will be here.
      2. Master DB (explicit master_pg connection) — fallback for the rare
         edge case where the vehicle drove between plazas faster than the
         30-second sync window. Only tried if local returns nothing.

    Note: we never lock the trip here. select_for_update() is called inside
    process_exit() after we confirm the trip exists.
    """
    from django.db import connections

    # 1. Local lookup (covers same-plaza and synced cross-plaza entries)
    trip = TollTrip.objects.select_related('entry_plaza', 'vehicle').filter(
        vehicle=vehicle, status=TripStatus.ACTIVE
    ).first()
    if trip:
        return trip

    # 2. Master fallback (vehicle arrived faster than sync interval)
    try:
        with connections['master_pg'].cursor() as cur:
            cur.execute("""
                SELECT id FROM toll_trips
                WHERE vehicle_id = %s AND status = 'active'
                LIMIT 1
            """, [str(vehicle.id)])
            row = cur.fetchone()
            if row:
                # Re-fetch via ORM so we get proper model instance with relations
                return TollTrip.objects.select_related(
                    'entry_plaza', 'vehicle'
                ).filter(id=row[0]).first()
    except Exception as exc:
        logger.warning("Master fallback trip lookup failed: %s", exc)

    return None
```

- [ ] **Step 3: Use _find_active_trip in ExitService**

In `apps/tolls/services.py`, inside `ExitService.process_exit`, find:

```python
        # 2. Lock active trip
        try:
            trip = TollTrip.objects.select_for_update().select_related(
                'entry_plaza', 'vehicle'
            ).get(vehicle=tag.vehicle, status=TripStatus.ACTIVE)
        except TollTrip.DoesNotExist:
            return {'success': False, 'reason': 'No active trip found for this vehicle'}
```

Replace with:

```python
        # 2. Find active trip (local first, master fallback for cross-plaza)
        trip = _find_active_trip(tag.vehicle)
        if not trip:
            return {'success': False, 'reason': 'No active trip found for this vehicle'}

        # Re-fetch with lock now that we know the trip exists locally
        try:
            trip = TollTrip.objects.select_for_update().select_related(
                'entry_plaza', 'vehicle'
            ).get(id=trip.id, status=TripStatus.ACTIVE)
        except TollTrip.DoesNotExist:
            return {'success': False, 'reason': 'Trip was already processed'}
```

- [ ] **Step 4: Test exit lookup**

```bash
python manage.py shell -c "
from apps.vehicles.models import Vehicle
from apps.tolls.services import _find_active_trip
v = Vehicle.objects.first()
trip = _find_active_trip(v)
print('Trip found:', trip.id if trip else 'None — expected if no active trip')
"
```

- [ ] **Step 5: Commit**

```bash
git add apps/tolls/services.py
git commit -m "feat: exit service local-first active trip lookup with master fallback"
```

---

## Task 8: Auto-Start Sync Agent in AppConfig

**Files:**
- Modify: `apps/tolls/apps.py`

- [ ] **Step 1: Update apps.py ready() method**

Replace the current `ready()` content in `apps/tolls/apps.py`:

```python
import os
import threading
from django.apps import AppConfig


class TollsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.tolls'
    label = 'tolls'

    def ready(self):
        # Only in actual server process, not reloader monitor or management commands
        if os.environ.get('RUN_MAIN') != 'true':
            return

        # Start PostgreSQL sync agent
        from apps.tolls.sync.agent import start as start_sync
        start_sync()

        # Start ANPR gate if config exists
        base_dir = os.path.dirname(
            os.path.abspath(
                os.path.join(os.path.dirname(__file__), '..', '..', 'manage.py')
            )
        )
        cfg_path = os.path.join(base_dir, 'anpr_config.ini')
        if os.path.exists(cfg_path):
            threading.Thread(
                target=self._start_anpr_gate,
                args=(cfg_path,),
                name='anpr-gate',
                daemon=True,
            ).start()

    def _start_anpr_gate(self, cfg_path: str):
        import configparser
        import logging
        log = logging.getLogger('apps.tolls.anpr_gate')

        try:
            from apps.tolls.management.commands.run_gate import resolve_plaza_lane
            from apps.tolls.management.commands.run_anpr_gate import AnprGateController
        except Exception as exc:
            log.error("[anpr] Import error: %s", exc)
            return

        cfg = configparser.ConfigParser()
        cfg.read(cfg_path)

        gate_mode     = cfg.get('gate', 'mode',          fallback='entry').strip().lower()
        plaza_id      = cfg.get('gate', 'plaza_id',      fallback='').strip()
        plaza_code    = cfg.get('gate', 'plaza_code',    fallback='').strip().upper()
        lane_id       = cfg.get('gate', 'lane_id',       fallback='').strip() or None
        lane_number   = cfg.get('gate', 'lane_number',   fallback='').strip() or None
        plate_cooldown = float(cfg.get('gate', 'plate_cooldown', fallback='5.0'))
        ws_url        = cfg.get('anpr', 'ws_url',        fallback='ws://localhost:3003')
        serial_port   = cfg.get('barrier', 'port',       fallback='/dev/ttyUSB0')
        serial_baud   = int(cfg.get('barrier', 'baudrate', fallback='115200'))
        open_secs     = float(cfg.get('barrier', 'open_seconds', fallback='2.0'))
        display_ip    = cfg.get('display', 'display_ip', fallback='192.168.78.12')

        try:
            plaza_id, lane_id = resolve_plaza_lane(plaza_code, plaza_id, lane_number, lane_id)
        except Exception as exc:
            log.error("[anpr] Plaza/lane config error: %s", exc)
            return

        class _Stdout:
            def write(self, msg):
                log.info(msg.strip())

        gate = AnprGateController(
            gate_mode=gate_mode,
            plaza_id=plaza_id,
            lane_id=lane_id,
            serial_port=serial_port,
            serial_baud=serial_baud,
            open_secs=open_secs,
            display_ip=display_ip,
            tag_cooldown=plate_cooldown,
            stdout=_Stdout(),
        )

        log.info("[anpr] Gate thread started — connecting to %s", ws_url)
        gate.run_ws(ws_url)
```

- [ ] **Step 2: Test server startup**

```bash
python manage.py runserver
```

Expected in logs within 5 seconds:
```
[sync] Agent started — interval=30s
[sync] Background thread started
[sync] pull={...}  push={...}
```

- [ ] **Step 3: Commit**

```bash
git add apps/tolls/apps.py
git commit -m "feat: auto-start PostgreSQL sync agent on Django startup"
```

---

## Task 9: End-to-End Test

- [ ] **Step 1: Run sync once manually and verify data in local**

```bash
python manage.py run_sync_agent --once

python manage.py shell -c "
from apps.tolls.models import Plaza, SyncLog
print('Plazas in local:', Plaza.objects.count())
print('Sync log:')
for s in SyncLog.objects.all():
    print(f'  {s.table_name}: pull={s.last_pull_at}  push={s.last_push_at}')
"
```

- [ ] **Step 2: Simulate multi-plaza scenario**

```bash
# 1. Create entry at "Plaza A" (entry mode)
python manage.py shell -c "
from apps.tolls.models import TollTrip, TripStatus, Plaza, TollLane
from apps.vehicles.models import Vehicle, Tag
from apps.accounts.models import Account
v = Vehicle.objects.first()
plaza = Plaza.objects.first()
tag = v.tag
account = Account.objects.get(vehicle=v)
trip = TollTrip.objects.create(
    vehicle=v, tag=tag, account=account,
    entry_plaza=plaza, status=TripStatus.ACTIVE
)
print('Entry trip created:', trip.id)
"

# 2. Run sync (simulates Plaza A pushing to master, Plaza B pulling)
python manage.py run_sync_agent --once

# 3. Verify exit finds the trip via local lookup
python manage.py shell -c "
from apps.vehicles.models import Vehicle
from apps.tolls.services import _find_active_trip
v = Vehicle.objects.first()
trip = _find_active_trip(v)
print('Trip found:', trip.id if trip else 'NOT FOUND')
print('Entry plaza:', trip.entry_plaza if trip else '-')
"
```

Expected: `Trip found: <uuid>  Entry plaza: <plaza_name>`

- [ ] **Step 3: Final commit**

```bash
git add .
git commit -m "feat: complete PostgreSQL sync agent — pull/push + local-first exit lookup"
```

---

## Summary — What Was Built

```
Master DB (192.168.78.200)
    ↑ push (trips, transactions)
    ↓ pull (all reference data + active trips)
Local DB (localhost)
    ↑ always used by gate for entry/exit
    ↓ exit lookup: local first → master fallback
```

| Scenario | Result |
|----------|--------|
| Master online, normal operation | All ops on master via default multi-host |
| Master down, vehicle enters | Entry on local → pushed to master when back |
| Vehicle exits different plaza | Local has trip from pull → exit succeeds |
| Sync interval missed (fast vehicle) | Master fallback in ExitService catches it |
| Balance deduction | Atomic on master (SELECT FOR UPDATE) |
