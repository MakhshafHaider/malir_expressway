"""
Offline cache for booth PCs — SQLite-backed local database.

Responsibilities:
  - Schema creation and maintenance.
  - Syncing data FROM central PostgreSQL INTO local SQLite (read-only direction
    for financial data; the central DB is the single source of truth).
  - Providing read access to cached data so the gate can validate tags and look
    up rates when the central DB is unreachable.

NOT responsible for:
  - Offline exit logic or idempotency (see offline_exit_service.py).
  - Reconciliation / syncing offline events back to PostgreSQL
    (see reconciliation_service.py).

SQLite pragmas applied on every connection:
    PRAGMA journal_mode=WAL;
    PRAGMA synchronous=FULL;
    PRAGMA foreign_keys=ON;
    PRAGMA busy_timeout=5000;
"""

import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── DB error detection ────────────────────────────────────────────────────────

_DB_ERRORS = None  # lazily populated tuple of exception types


def _is_db_error(exc: BaseException) -> bool:
    """Return True if *exc* looks like a PostgreSQL / Django connectivity error."""
    global _DB_ERRORS
    if _DB_ERRORS is None:
        try:
            from django.db import OperationalError, DatabaseError
            import psycopg2
            _DB_ERRORS = (OperationalError, DatabaseError, psycopg2.OperationalError)
        except Exception:
            from django.db import OperationalError, DatabaseError
            _DB_ERRORS = (OperationalError, DatabaseError)
    return isinstance(exc, _DB_ERRORS)


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_db_path() -> str:
    """Return default path: {manage.py dir}/offline_cache.db."""
    manage_dir = os.path.dirname(
        os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', '..', 'manage.py')
        )
    )
    return os.path.join(manage_dir, 'offline_cache.db')


def _connect(db_path: str) -> sqlite3.Connection:
    """Open a SQLite connection with required pragmas applied."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=FULL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tag_cache (
    tag_serial          TEXT PRIMARY KEY,
    vehicle_id          TEXT,
    plate_number        TEXT,
    vehicle_type        TEXT,
    vehicle_status      TEXT,
    account_id          TEXT,
    last_known_balance  REAL,
    tag_status          TEXT,
    expiry_date         TEXT,
    synced_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS toll_rate_cache (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_plaza_id  TEXT NOT NULL,
    exit_plaza_id   TEXT NOT NULL,
    vehicle_type    TEXT NOT NULL,
    rate            REAL NOT NULL,
    effective_from  TEXT NOT NULL,
    synced_at       TEXT NOT NULL,
    UNIQUE(entry_plaza_id, exit_plaza_id, vehicle_type, effective_from)
);

CREATE TABLE IF NOT EXISTS active_trip_cache (
    tag_serial          TEXT PRIMARY KEY,
    trip_id             TEXT NOT NULL,
    entry_plaza_id      TEXT NOT NULL,
    entry_plaza_code    TEXT,
    entry_time          TEXT NOT NULL,
    vehicle_id          TEXT,
    vehicle_plate       TEXT,
    vehicle_type        TEXT,
    synced_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offline_exit_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key     TEXT NOT NULL UNIQUE,
    tag_serial          TEXT NOT NULL,
    vehicle_id          TEXT,
    plate_number        TEXT,
    exit_plaza_id       TEXT NOT NULL,
    exit_lane_id        TEXT,
    exit_time           TEXT NOT NULL,
    estimated_amount    REAL,
    sync_status         TEXT NOT NULL DEFAULT 'PENDING',
    sync_attempts       INTEGER NOT NULL DEFAULT 0,
    error_message       TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type  TEXT NOT NULL,
    event_id    INTEGER,
    status      TEXT NOT NULL,
    message     TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gate_event_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type      TEXT NOT NULL,
    tag_serial      TEXT,
    vehicle_plate   TEXT,
    plaza_id        TEXT,
    lane_id         TEXT,
    result          TEXT NOT NULL,
    reason          TEXT,
    offline         INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);
"""


def init_db(db_path: Optional[str] = None) -> str:
    """Create schema on the SQLite database, return the db_path used."""
    if db_path is None:
        db_path = get_db_path()
    db_path = os.path.abspath(db_path)

    conn = _connect(db_path)
    try:
        conn.executescript(_SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()

    logger.info("[cache] SQLite schema initialised at %s", db_path)
    return db_path


# ── CacheSync ─────────────────────────────────────────────────────────────────

class CacheSync:
    """
    Pulls data from the central PostgreSQL database and writes it into the
    local SQLite cache.  All writes are protected by self._lock.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path: str = init_db(db_path)
        self._lock = threading.Lock()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        return _connect(self.db_path)

    def _log_sync(
        self,
        conn: sqlite3.Connection,
        event_type: str,
        status: str,
        message: str,
        event_id: Optional[int] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO sync_logs (event_type, event_id, status, message, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (event_type, event_id, status, message, now),
        )

    # ── sync_tags ─────────────────────────────────────────────────────────────

    def sync_tags(self) -> int:
        """
        Sync Tag + Vehicle + Account data from central DB into tag_cache.
        Returns the number of rows upserted.
        """
        from apps.vehicles.models import Tag
        from apps.accounts.models import Account

        now_iso = datetime.now(timezone.utc).isoformat()
        rows = []

        try:
            tags = Tag.objects.select_related('vehicle').filter(
                status='active'
            ).iterator(chunk_size=500)

            for tag in tags:
                vehicle = tag.vehicle
                account_id = None
                balance = 0.0

                if vehicle is not None:
                    try:
                        acct = Account.objects.get(vehicle=vehicle)
                        account_id = str(acct.id)
                        balance = float(acct.balance)
                    except Account.DoesNotExist:
                        pass

                expiry_str = (
                    tag.expiry_date.isoformat() if tag.expiry_date else None
                )

                rows.append((
                    tag.tag_serial,
                    str(tag.vehicle_id) if tag.vehicle_id else None,
                    vehicle.plate_number if vehicle else None,
                    vehicle.vehicle_type if vehicle else None,
                    vehicle.status if vehicle else None,
                    account_id,
                    balance,
                    tag.status,
                    expiry_str,
                    now_iso,
                ))
        except Exception:
            logger.exception("[cache] sync_tags: error reading from central DB")
            raise

        with self._lock:
            conn = self._conn()
            try:
                conn.executemany(
                    """
                    INSERT INTO tag_cache
                        (tag_serial, vehicle_id, plate_number, vehicle_type,
                         vehicle_status, account_id, last_known_balance,
                         tag_status, expiry_date, synced_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tag_serial) DO UPDATE SET
                        vehicle_id          = excluded.vehicle_id,
                        plate_number        = excluded.plate_number,
                        vehicle_type        = excluded.vehicle_type,
                        vehicle_status      = excluded.vehicle_status,
                        account_id          = excluded.account_id,
                        last_known_balance  = excluded.last_known_balance,
                        tag_status          = excluded.tag_status,
                        expiry_date         = excluded.expiry_date,
                        synced_at           = excluded.synced_at
                    """,
                    rows,
                )
                self._log_sync(
                    conn,
                    event_type='sync_tags',
                    status='OK',
                    message=f"Upserted {len(rows)} tags",
                )
                conn.commit()
            except Exception:
                conn.rollback()
                logger.exception("[cache] sync_tags: SQLite write error")
                raise
            finally:
                conn.close()

        logger.debug("[cache] sync_tags: upserted %d rows", len(rows))
        return len(rows)

    # ── sync_rates ────────────────────────────────────────────────────────────

    def sync_rates(self) -> int:
        """
        Sync TollRate records from central DB into toll_rate_cache.
        Returns the number of rows upserted.
        """
        from apps.tolls.models import TollRate
        from django.utils import timezone as dj_timezone

        now_iso = datetime.now(timezone.utc).isoformat()
        rows = []

        try:
            rates = TollRate.objects.filter(
                effective_from__lte=dj_timezone.now().date()
            ).values(
                'entry_plaza_id', 'exit_plaza_id', 'vehicle_type',
                'rate', 'effective_from',
            ).iterator(chunk_size=500)

            for r in rates:
                rows.append((
                    str(r['entry_plaza_id']),
                    str(r['exit_plaza_id']),
                    r['vehicle_type'],
                    float(r['rate']),
                    r['effective_from'].isoformat(),
                    now_iso,
                ))
        except Exception:
            logger.exception("[cache] sync_rates: error reading from central DB")
            raise

        with self._lock:
            conn = self._conn()
            try:
                conn.executemany(
                    """
                    INSERT INTO toll_rate_cache
                        (entry_plaza_id, exit_plaza_id, vehicle_type, rate,
                         effective_from, synced_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(entry_plaza_id, exit_plaza_id, vehicle_type, effective_from)
                    DO UPDATE SET
                        rate      = excluded.rate,
                        synced_at = excluded.synced_at
                    """,
                    rows,
                )
                self._log_sync(
                    conn,
                    event_type='sync_rates',
                    status='OK',
                    message=f"Upserted {len(rows)} rates",
                )
                conn.commit()
            except Exception:
                conn.rollback()
                logger.exception("[cache] sync_rates: SQLite write error")
                raise
            finally:
                conn.close()

        logger.debug("[cache] sync_rates: upserted %d rows", len(rows))
        return len(rows)

    # ── sync_active_trips ─────────────────────────────────────────────────────

    def sync_active_trips(self) -> int:
        """
        Sync ACTIVE TollTrip records from central DB into active_trip_cache.
        Removes stale entries that are no longer active in the central DB.
        Returns the number of rows upserted.
        """
        from apps.tolls.models import TollTrip, TripStatus

        now_iso = datetime.now(timezone.utc).isoformat()
        rows = []
        active_tag_serials = []

        try:
            trips = TollTrip.objects.filter(
                status=TripStatus.ACTIVE
            ).select_related(
                'tag', 'vehicle', 'entry_plaza'
            ).iterator(chunk_size=500)

            for trip in trips:
                tag_serial = trip.tag.tag_serial if trip.tag else None
                if not tag_serial:
                    continue
                active_tag_serials.append(tag_serial)
                rows.append((
                    tag_serial,
                    str(trip.id),
                    str(trip.entry_plaza_id),
                    trip.entry_plaza.code if trip.entry_plaza else None,
                    trip.entry_time.isoformat(),
                    str(trip.vehicle_id) if trip.vehicle_id else None,
                    trip.vehicle.plate_number if trip.vehicle else None,
                    trip.vehicle.vehicle_type if trip.vehicle else None,
                    now_iso,
                ))
        except Exception:
            logger.exception("[cache] sync_active_trips: error reading central DB")
            raise

        with self._lock:
            conn = self._conn()
            try:
                # Upsert current active trips
                conn.executemany(
                    """
                    INSERT INTO active_trip_cache
                        (tag_serial, trip_id, entry_plaza_id, entry_plaza_code,
                         entry_time, vehicle_id, vehicle_plate, vehicle_type, synced_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tag_serial) DO UPDATE SET
                        trip_id         = excluded.trip_id,
                        entry_plaza_id  = excluded.entry_plaza_id,
                        entry_plaza_code= excluded.entry_plaza_code,
                        entry_time      = excluded.entry_time,
                        vehicle_id      = excluded.vehicle_id,
                        vehicle_plate   = excluded.vehicle_plate,
                        vehicle_type    = excluded.vehicle_type,
                        synced_at       = excluded.synced_at
                    """,
                    rows,
                )

                # Remove trips that are no longer active
                if active_tag_serials:
                    placeholders = ','.join('?' * len(active_tag_serials))
                    conn.execute(
                        f"DELETE FROM active_trip_cache "
                        f"WHERE tag_serial NOT IN ({placeholders})",
                        active_tag_serials,
                    )
                else:
                    # No active trips in central DB — clear everything
                    conn.execute("DELETE FROM active_trip_cache")

                self._log_sync(
                    conn,
                    event_type='sync_active_trips',
                    status='OK',
                    message=f"Upserted {len(rows)} active trips",
                )
                conn.commit()
            except Exception:
                conn.rollback()
                logger.exception("[cache] sync_active_trips: SQLite write error")
                raise
            finally:
                conn.close()

        logger.debug("[cache] sync_active_trips: upserted %d rows", len(rows))
        return len(rows)

    # ── run_full_sync ─────────────────────────────────────────────────────────

    def run_full_sync(self) -> dict:
        """
        Run all three sync operations.  Returns a summary dict.
        Does not raise — individual failures are logged and reported in the
        returned summary so the caller can decide how to proceed.
        """
        summary: dict = {
            'tags': 0,
            'rates': 0,
            'active_trips': 0,
            'errors': [],
        }

        for name, method in [
            ('tags', self.sync_tags),
            ('rates', self.sync_rates),
            ('active_trips', self.sync_active_trips),
        ]:
            try:
                summary[name] = method()
            except Exception as exc:
                msg = f"{name}: {exc.__class__.__name__}: {exc}"
                logger.error("[cache] full_sync error — %s", msg)
                summary['errors'].append(msg)

        logger.info(
            "[cache] full_sync done — tags=%d rates=%d trips=%d errors=%d",
            summary['tags'],
            summary['rates'],
            summary['active_trips'],
            len(summary['errors']),
        )
        return summary


# ── CacheReader ───────────────────────────────────────────────────────────────

class CacheReader:
    """
    Read-only interface to the local SQLite cache.
    Used by gate logic when the central DB is unreachable.
    All methods return plain Python dicts (or None).
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path: str = os.path.abspath(db_path or get_db_path())

    def _conn(self) -> sqlite3.Connection:
        return _connect(self.db_path)

    # ── get_tag ───────────────────────────────────────────────────────────────

    def get_tag(self, tag_serial: str) -> Optional[dict]:
        """
        Return a dict with tag/vehicle/account data, or None if not cached.

        Keys: tag_serial, vehicle_id, plate_number, vehicle_type,
              vehicle_status, account_id, last_known_balance, tag_status,
              expiry_date, synced_at
        """
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT tag_serial, vehicle_id, plate_number, vehicle_type, "
                "       vehicle_status, account_id, last_known_balance, "
                "       tag_status, expiry_date, synced_at "
                "FROM tag_cache WHERE tag_serial = ?",
                (tag_serial,),
            ).fetchone()
            if row is None:
                return None
            return dict(row)
        except Exception:
            logger.exception("[cache] get_tag error for %s", tag_serial)
            return None
        finally:
            conn.close()

    # ── get_rate ──────────────────────────────────────────────────────────────

    def get_rate(
        self,
        entry_plaza_id: str,
        exit_plaza_id: str,
        vehicle_type: str,
    ) -> Optional[float]:
        """
        Return the most recently effective rate (as a float) for the given
        plaza pair and vehicle type, or None if not cached.
        """
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT rate FROM toll_rate_cache "
                "WHERE entry_plaza_id = ? "
                "  AND exit_plaza_id  = ? "
                "  AND vehicle_type   = ? "
                "ORDER BY effective_from DESC "
                "LIMIT 1",
                (entry_plaza_id, exit_plaza_id, vehicle_type),
            ).fetchone()
            if row is None:
                return None
            return float(row['rate'])
        except Exception:
            logger.exception(
                "[cache] get_rate error for %s→%s %s",
                entry_plaza_id, exit_plaza_id, vehicle_type,
            )
            return None
        finally:
            conn.close()

    # ── get_active_trip ───────────────────────────────────────────────────────

    def get_active_trip(self, tag_serial: str) -> Optional[dict]:
        """
        Return the cached active trip for the given tag, or None.

        Keys: tag_serial, trip_id, entry_plaza_id, entry_plaza_code,
              entry_time, vehicle_id, vehicle_plate, vehicle_type, synced_at
        """
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT tag_serial, trip_id, entry_plaza_id, entry_plaza_code, "
                "       entry_time, vehicle_id, vehicle_plate, vehicle_type, synced_at "
                "FROM active_trip_cache WHERE tag_serial = ?",
                (tag_serial,),
            ).fetchone()
            if row is None:
                return None
            return dict(row)
        except Exception:
            logger.exception("[cache] get_active_trip error for %s", tag_serial)
            return None
        finally:
            conn.close()

    # ── get_tag_cache_age_hours ───────────────────────────────────────────────

    def get_tag_cache_age_hours(self, tag_serial: str) -> float:
        """
        Return how many hours ago the tag data was last synced from central DB.
        Returns a very large number (999.0) if the tag is not in the cache or
        the synced_at field is missing / unparseable.
        """
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT synced_at FROM tag_cache WHERE tag_serial = ?",
                (tag_serial,),
            ).fetchone()
            if row is None or not row['synced_at']:
                return 999.0

            synced_at = datetime.fromisoformat(row['synced_at'])
            if synced_at.tzinfo is None:
                synced_at = synced_at.replace(tzinfo=timezone.utc)

            delta = datetime.now(timezone.utc) - synced_at
            return delta.total_seconds() / 3600.0
        except Exception:
            logger.exception("[cache] get_tag_cache_age_hours error for %s", tag_serial)
            return 999.0
        finally:
            conn.close()


# ── Background sync thread ────────────────────────────────────────────────────

def start_sync_thread(
    db_path: str,
    interval_seconds: int = 60,
) -> threading.Thread:
    """
    Start a background daemon thread that calls CacheSync.run_full_sync()
    every *interval_seconds*.  Returns the Thread object.
    """
    sync = CacheSync(db_path)

    def _loop() -> None:
        logger.info(
            "[cache] Sync thread started — interval=%ds db=%s",
            interval_seconds, db_path,
        )
        while True:
            try:
                sync.run_full_sync()
            except Exception:
                logger.exception("[cache] Unexpected error in sync thread")
            time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, name="offline-cache-sync", daemon=True)
    t.start()
    return t


# ── Legacy shim — keeps old code that calls get_cache() from breaking ─────────

class _LegacyCache:
    """Thin wrapper so old callers (run_gate.py handle) still work."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = init_db(db_path)
        self._sync_thread: Optional[threading.Thread] = None

    def start_sync(self) -> None:
        if self._sync_thread is None:
            self._sync_thread = start_sync_thread(self.db_path)

    @property
    def is_online(self) -> bool:
        return True  # status tracked elsewhere now


_cache: Optional[_LegacyCache] = None


def get_cache(db_path: Optional[str] = None) -> _LegacyCache:
    global _cache
    if _cache is None:
        _cache = _LegacyCache(db_path)
    return _cache
