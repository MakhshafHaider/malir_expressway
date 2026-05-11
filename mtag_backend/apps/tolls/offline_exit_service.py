"""
Offline exit service for booth PCs.

Handles RFID tag scans at exit booths when the central PostgreSQL database
is unreachable.  All exit events are written to the local SQLite
offline_exit_events table with a unique idempotency key so they can be
replayed exactly once against the central DB when connectivity is restored.

Balance is NOT deducted from SQLite — deduction happens during reconciliation
against the authoritative central DB balance.

Trip status is NOT changed locally — the active_trip_cache is read-only here.
"""

import hashlib
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from apps.tolls.offline_cache import CacheReader, _connect, get_db_path, init_db

logger = logging.getLogger(__name__)

# ── Business-rule constants ───────────────────────────────────────────────────

CACHE_STALENESS_LIMIT_HOURS: float = 6.0
MIN_CACHED_BALANCE: Decimal = Decimal('50.00')
MAX_OFFLINE_EXITS_PER_TAG: int = 3


# ── Idempotency key ───────────────────────────────────────────────────────────

def make_exit_idempotency_key(
    plaza_code: str,
    lane_number: int,
    tag_serial: str,
    exit_time: datetime,
) -> str:
    """
    Generate a deterministic idempotency key for an offline exit event.

    The key is bucketed to the nearest 5-minute interval to absorb retries
    and minor clock skew between booth PC and server.
    """
    bucket_minute = (exit_time.minute // 5) * 5
    bucket = exit_time.replace(minute=bucket_minute, second=0, microsecond=0)
    raw = (
        f"EXIT_{plaza_code}_{lane_number}_{tag_serial}_"
        f"{bucket.strftime('%Y%m%d%H%M')}"
    )
    digest = hashlib.sha256(raw.encode()).hexdigest()[:32]
    return f"OEXIT_{digest}"


# ── OfflineExitService ────────────────────────────────────────────────────────

class OfflineExitService:
    """
    Process an RFID tag scan at an exit booth when the central DB is
    unreachable.

    All SQLite writes are guarded by self._lock for thread safety.
    """

    def __init__(
        self,
        db_path: Optional[str],
        plaza_code: str,
        lane_number: int,
        plaza_id: str,
        lane_id: Optional[str],
    ) -> None:
        self.db_path: str = init_db(db_path or get_db_path())
        self.plaza_code: str = plaza_code
        self.lane_number: int = int(lane_number)
        self.plaza_id: str = plaza_id
        self.lane_id: Optional[str] = lane_id
        self._reader = CacheReader(self.db_path)
        self._lock = threading.Lock()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        return _connect(self.db_path)

    def _count_unsynced_exits(self, conn: sqlite3.Connection, tag_serial: str) -> int:
        """Count offline exit events for this tag that have not yet been synced."""
        row = conn.execute(
            "SELECT COUNT(*) FROM offline_exit_events "
            "WHERE tag_serial = ? AND sync_status IN ('PENDING', 'FAILED', 'PROCESSING')",
            (tag_serial,),
        ).fetchone()
        return row[0] if row else 0

    def _log_gate_event(
        self,
        conn: sqlite3.Connection,
        tag_serial: str,
        vehicle_plate: Optional[str],
        result: str,
        reason: Optional[str],
        offline: bool,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO gate_event_logs "
            "(event_type, tag_serial, vehicle_plate, plaza_id, lane_id, "
            " result, reason, offline, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                'exit',
                tag_serial,
                vehicle_plate,
                self.plaza_id,
                self.lane_id,
                result,
                reason,
                1 if offline else 0,
                now,
            ),
        )

    def _log_sync_event(
        self,
        conn: sqlite3.Connection,
        event_id: Optional[int],
        status: str,
        message: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO sync_logs (event_type, event_id, status, message, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ('offline_exit', event_id, status, message, now),
        )

    # ── process_exit_offline ──────────────────────────────────────────────────

    def process_exit_offline(self, tag_serial: str) -> dict:
        """
        Main entry point: validate the tag against the local cache and, if
        allowed, record an offline exit event for later reconciliation.

        Returns a result dict with at minimum the keys:
            success (bool)
            reason  (str)  — present on failure
        """
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        # ── Step 1: Read tag from cache ────────────────────────────────────────
        tag = self._reader.get_tag(tag_serial)

        if tag is None:
            logger.warning(
                "[offline_exit] Tag %s not in local cache — rejecting",
                tag_serial,
            )
            with self._lock:
                conn = self._conn()
                try:
                    self._log_gate_event(
                        conn, tag_serial, None, 'DENIED',
                        'Tag not in local cache', True,
                    )
                    conn.commit()
                finally:
                    conn.close()
            return {
                'success': False,
                'reason': 'Tag not in local cache — cannot validate offline',
            }

        plate_number: Optional[str] = tag.get('plate_number')
        vehicle_type: Optional[str] = tag.get('vehicle_type')
        vehicle_id: Optional[str] = tag.get('vehicle_id')

        # ── Step 2: Check cache staleness ──────────────────────────────────────
        age_hours = self._reader.get_tag_cache_age_hours(tag_serial)

        if age_hours > CACHE_STALENESS_LIMIT_HOURS:
            logger.warning(
                "[offline_exit] Tag %s cache age %.2fh > %.1fh limit — "
                "opening barrier with NEEDS_MANUAL_REVIEW flag",
                tag_serial, age_hours, CACHE_STALENESS_LIMIT_HOURS,
            )
            idempotency_key = make_exit_idempotency_key(
                self.plaza_code, self.lane_number, tag_serial, now
            )
            with self._lock:
                conn = self._conn()
                try:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO offline_exit_events
                            (idempotency_key, tag_serial, vehicle_id, plate_number,
                             exit_plaza_id, exit_lane_id, exit_time, estimated_amount,
                             sync_status, sync_attempts, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'NEEDS_MANUAL_REVIEW', 0, ?, ?)
                        """,
                        (
                            idempotency_key, tag_serial, vehicle_id, plate_number,
                            self.plaza_id, self.lane_id, now_iso, now_iso, now_iso,
                        ),
                    )
                    event_id_row = conn.execute(
                        "SELECT id FROM offline_exit_events WHERE idempotency_key = ?",
                        (idempotency_key,),
                    ).fetchone()
                    event_id = event_id_row[0] if event_id_row else None

                    self._log_gate_event(
                        conn, tag_serial, plate_number, 'ALLOWED_STALE_CACHE',
                        f'Cache age {age_hours:.2f}h — manual review required', True,
                    )
                    self._log_sync_event(
                        conn, event_id, 'NEEDS_MANUAL_REVIEW',
                        f'Tag cache stale ({age_hours:.2f}h) — flagged for review',
                    )
                    conn.commit()
                finally:
                    conn.close()

            return {
                'success': True,
                'offline': True,
                'needs_manual_review': True,
                'vehicle': plate_number,
                'vehicle_type': vehicle_type,
                'reason': 'Cache stale — flagged for manual review',
                'idempotency_key': idempotency_key,
            }

        # ── Step 3: Tag status check ───────────────────────────────────────────
        tag_status: str = tag.get('tag_status') or ''
        if tag_status != 'active':
            logger.info(
                "[offline_exit] Tag %s rejected — tag_status=%s", tag_serial, tag_status
            )
            with self._lock:
                conn = self._conn()
                try:
                    self._log_gate_event(
                        conn, tag_serial, plate_number, 'DENIED',
                        f'Tag status is {tag_status}', True,
                    )
                    conn.commit()
                finally:
                    conn.close()
            return {
                'success': False,
                'reason': f'Tag is {tag_status}',
            }

        # ── Step 4: Vehicle status check ──────────────────────────────────────
        vehicle_status: str = tag.get('vehicle_status') or ''
        if vehicle_status != 'active':
            logger.info(
                "[offline_exit] Tag %s rejected — vehicle_status=%s",
                tag_serial, vehicle_status,
            )
            with self._lock:
                conn = self._conn()
                try:
                    self._log_gate_event(
                        conn, tag_serial, plate_number, 'DENIED',
                        f'Vehicle status is {vehicle_status}', True,
                    )
                    conn.commit()
                finally:
                    conn.close()
            return {
                'success': False,
                'reason': f'Vehicle is {vehicle_status}',
            }

        # ── Step 5: Minimum balance check ─────────────────────────────────────
        last_known_balance = Decimal(str(tag.get('last_known_balance') or 0))
        if last_known_balance < MIN_CACHED_BALANCE:
            logger.info(
                "[offline_exit] Tag %s rejected — balance %.2f < %.2f",
                tag_serial, last_known_balance, MIN_CACHED_BALANCE,
            )
            with self._lock:
                conn = self._conn()
                try:
                    self._log_gate_event(
                        conn, tag_serial, plate_number, 'DENIED',
                        f'Insufficient cached balance ({last_known_balance})', True,
                    )
                    conn.commit()
                finally:
                    conn.close()
            return {
                'success': False,
                'reason': 'Insufficient cached balance',
                'last_known_balance': str(last_known_balance),
                'minimum_required': str(MIN_CACHED_BALANCE),
            }

        # ── Step 6: Max unsynced exits check ─────────────────────────────────
        idempotency_key = make_exit_idempotency_key(
            self.plaza_code, self.lane_number, tag_serial, now
        )

        with self._lock:
            conn = self._conn()
            try:
                unsynced = self._count_unsynced_exits(conn, tag_serial)

                if unsynced >= MAX_OFFLINE_EXITS_PER_TAG:
                    logger.warning(
                        "[offline_exit] Tag %s rejected — %d unsynced exits >= limit %d",
                        tag_serial, unsynced, MAX_OFFLINE_EXITS_PER_TAG,
                    )
                    self._log_gate_event(
                        conn, tag_serial, plate_number, 'DENIED',
                        f'Too many unsynced offline exits ({unsynced})', True,
                    )
                    conn.commit()
                    return {
                        'success': False,
                        'reason': (
                            f'Too many unsynced offline exits for this tag '
                            f'({unsynced}/{MAX_OFFLINE_EXITS_PER_TAG}). '
                            f'Sync required before further offline exits.'
                        ),
                    }

                # ── Step 7: Insert offline exit event (idempotent) ────────────
                try:
                    conn.execute(
                        """
                        INSERT INTO offline_exit_events
                            (idempotency_key, tag_serial, vehicle_id, plate_number,
                             exit_plaza_id, exit_lane_id, exit_time, estimated_amount,
                             sync_status, sync_attempts, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'PENDING', 0, ?, ?)
                        """,
                        (
                            idempotency_key, tag_serial, vehicle_id, plate_number,
                            self.plaza_id, self.lane_id, now_iso, now_iso, now_iso,
                        ),
                    )
                    inserted = True
                except sqlite3.IntegrityError:
                    # UNIQUE conflict — this exact exit was already recorded (idempotent)
                    inserted = False
                    logger.info(
                        "[offline_exit] Duplicate idempotency_key %s — returning success (idempotent)",
                        idempotency_key,
                    )

                event_id_row = conn.execute(
                    "SELECT id FROM offline_exit_events WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                event_id = event_id_row[0] if event_id_row else None

                # ── Step 8: Log to gate_event_logs ────────────────────────────
                self._log_gate_event(
                    conn, tag_serial, plate_number,
                    'ALLOWED' if inserted else 'ALLOWED_IDEMPOTENT',
                    None if inserted else 'Duplicate idempotency key — idempotent response',
                    True,
                )

                # ── Step 9: Log to sync_logs ──────────────────────────────────
                self._log_sync_event(
                    conn, event_id, 'PENDING',
                    'Offline exit event queued for reconciliation' if inserted
                    else 'Idempotent duplicate — already queued',
                )

                conn.commit()

            except Exception:
                conn.rollback()
                logger.exception(
                    "[offline_exit] SQLite write error for tag %s", tag_serial
                )
                raise
            finally:
                conn.close()

        logger.info(
            "[offline_exit] Tag %s plate=%s type=%s — exit event recorded key=%s",
            tag_serial, plate_number, vehicle_type, idempotency_key,
        )
        return {
            'success': True,
            'offline': True,
            'vehicle': plate_number,
            'vehicle_type': vehicle_type,
            'message': (
                'Offline exit recorded. '
                'Final amount will be deducted after sync.'
            ),
            'idempotency_key': idempotency_key,
        }
