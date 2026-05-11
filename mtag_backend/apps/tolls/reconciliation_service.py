"""
Reconciliation service — processes pending offline exit events against the
central PostgreSQL database.

When a booth PC reconnects after an offline period, the ReconciliationService
iterates over all PENDING (and retryable FAILED) offline_exit_events in the
local SQLite database and replays them against the central DB.

Each event is processed inside a single Django atomic transaction so that
balance deduction, trip completion and audit-transaction creation are all
committed or rolled back together.

Idempotency is guaranteed by checking Transaction.idempotency_key before
doing any writes — a duplicate sync attempt is silently marked SYNCED and
treated as a success.
"""

import logging
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from django.db import transaction as db_transaction

from apps.tolls.offline_cache import _connect, get_db_path, init_db

logger = logging.getLogger(__name__)

# Sync status string constants (no class needed — used as plain strings)
STATUS_PENDING = 'PENDING'
STATUS_PROCESSING = 'PROCESSING'
STATUS_SYNCED = 'SYNCED'
STATUS_FAILED = 'FAILED'
STATUS_NEEDS_MANUAL_REVIEW = 'NEEDS_MANUAL_REVIEW'

MAX_SYNC_ATTEMPTS = 5


class ReconciliationService:
    """
    Pulls pending offline_exit_events from local SQLite and syncs them to
    the central PostgreSQL database.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path: str = init_db(db_path or get_db_path())

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        return _connect(self.db_path)

    def _update_event_status(
        self,
        conn: sqlite3.Connection,
        event_id: int,
        status: str,
        error_message: Optional[str] = None,
        increment_attempts: bool = False,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if increment_attempts:
            conn.execute(
                "UPDATE offline_exit_events "
                "SET sync_status = ?, error_message = ?, "
                "    sync_attempts = sync_attempts + 1, updated_at = ? "
                "WHERE id = ?",
                (status, error_message, now, event_id),
            )
        else:
            conn.execute(
                "UPDATE offline_exit_events "
                "SET sync_status = ?, error_message = ?, updated_at = ? "
                "WHERE id = ?",
                (status, error_message, now, event_id),
            )
        conn.commit()

    def _write_sync_log(
        self,
        conn: sqlite3.Connection,
        event_id: int,
        status: str,
        message: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO sync_logs (event_type, event_id, status, message, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ('reconciliation', event_id, status, message, now),
        )
        conn.commit()

    # ── sync_all_pending ──────────────────────────────────────────────────────

    def sync_all_pending(self) -> dict:
        """
        Process all PENDING and retryable FAILED events.

        Returns a summary dict:
            {
                'total': int,
                'synced': int,
                'failed': int,
                'needs_manual_review': int,
                'skipped': int,
            }
        """
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT id, idempotency_key, tag_serial, vehicle_id, plate_number, "
                "       exit_plaza_id, exit_lane_id, exit_time, estimated_amount, "
                "       sync_status, sync_attempts "
                "FROM offline_exit_events "
                "WHERE sync_status IN (?, ?) AND sync_attempts < ? "
                "ORDER BY id ASC",
                (STATUS_PENDING, STATUS_FAILED, MAX_SYNC_ATTEMPTS),
            ).fetchall()
        finally:
            conn.close()

        summary = {
            'total': len(rows),
            'synced': 0,
            'failed': 0,
            'needs_manual_review': 0,
            'skipped': 0,
        }

        for row in rows:
            event = dict(row)
            try:
                success = self.sync_event(event)
                if success:
                    summary['synced'] += 1
                else:
                    # sync_event returned False without raising — check status
                    c = self._conn()
                    try:
                        r = c.execute(
                            "SELECT sync_status FROM offline_exit_events WHERE id = ?",
                            (event['id'],),
                        ).fetchone()
                        final_status = r['sync_status'] if r else STATUS_FAILED
                    finally:
                        c.close()
                    if final_status == STATUS_NEEDS_MANUAL_REVIEW:
                        summary['needs_manual_review'] += 1
                    else:
                        summary['failed'] += 1
            except Exception as exc:
                logger.exception(
                    "[reconciliation] Unhandled error for event %d: %s", event['id'], exc
                )
                summary['failed'] += 1

        logger.info(
            "[reconciliation] sync_all_pending complete — %s",
            summary,
        )
        return summary

    # ── sync_event ────────────────────────────────────────────────────────────

    def sync_event(self, event: dict) -> bool:
        """
        Process a single offline exit event against central PostgreSQL.

        Returns True on success (or if already synced), False on any failure
        that has been handled and recorded (e.g. NEEDS_MANUAL_REVIEW, FAILED).

        Raises only on programming errors (should not reach caller in normal
        operation — sync_all_pending catches exceptions).
        """
        event_id: int = event['id']
        idempotency_key: str = event['idempotency_key']
        tag_serial: str = event['tag_serial']

        sqlite_conn = self._conn()
        try:
            # ── 1. Mark as PROCESSING ─────────────────────────────────────────
            self._update_event_status(sqlite_conn, event_id, STATUS_PROCESSING)
        finally:
            sqlite_conn.close()

        try:
            result = self._sync_to_postgres(event)
        except Exception as exc:
            error_msg = f"{exc.__class__.__name__}: {exc}"
            logger.error(
                "[reconciliation] event %d (%s) failed: %s",
                event_id, idempotency_key, error_msg,
            )
            sqlite_conn = self._conn()
            try:
                self._update_event_status(
                    sqlite_conn, event_id, STATUS_FAILED,
                    error_message=error_msg,
                    increment_attempts=True,
                )
                self._write_sync_log(
                    sqlite_conn, event_id, STATUS_FAILED, error_msg
                )
            finally:
                sqlite_conn.close()
            return False

        # result is a tuple: (success: bool, status: str, message: str)
        success, final_status, message = result

        sqlite_conn = self._conn()
        try:
            self._update_event_status(
                sqlite_conn, event_id, final_status,
                error_message=None if success else message,
                increment_attempts=(not success and final_status == STATUS_FAILED),
            )
            self._write_sync_log(sqlite_conn, event_id, final_status, message)
        finally:
            sqlite_conn.close()

        return success

    def _sync_to_postgres(self, event: dict) -> tuple:
        """
        Perform the actual sync inside a Django atomic transaction.

        Returns (success, final_status, message).
        """
        from apps.vehicles.models import Tag
        from apps.accounts.models import Account, Transaction, TransactionType, TransactionStatus, TransactionSource
        from apps.tolls.models import TollRate, TollTrip, TripStatus, TollLane
        from django.utils import timezone as dj_timezone

        event_id: int = event['id']
        idempotency_key: str = event['idempotency_key']
        tag_serial: str = event['tag_serial']
        exit_plaza_id: str = event['exit_plaza_id']
        exit_lane_id: Optional[str] = event.get('exit_lane_id')
        exit_time_str: str = event['exit_time']

        try:
            exit_time = datetime.fromisoformat(exit_time_str)
            if exit_time.tzinfo is None:
                exit_time = exit_time.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError) as exc:
            return (
                False,
                STATUS_NEEDS_MANUAL_REVIEW,
                f"Cannot parse exit_time '{exit_time_str}': {exc}",
            )

        with db_transaction.atomic():
            # ── 2. Idempotency check ──────────────────────────────────────────
            if Transaction.objects.filter(idempotency_key=idempotency_key).exists():
                logger.info(
                    "[reconciliation] event %d already synced (idempotency_key=%s)",
                    event_id, idempotency_key,
                )
                return (
                    True,
                    STATUS_SYNCED,
                    'Already synced (idempotent duplicate)',
                )

            # ── 3. Look up Tag ────────────────────────────────────────────────
            try:
                tag = Tag.objects.select_related('vehicle').get(
                    tag_serial=tag_serial
                )
            except Tag.DoesNotExist:
                return (
                    False,
                    STATUS_NEEDS_MANUAL_REVIEW,
                    f"Tag '{tag_serial}' not found in central DB",
                )

            vehicle = tag.vehicle
            if vehicle is None:
                return (
                    False,
                    STATUS_NEEDS_MANUAL_REVIEW,
                    f"Tag '{tag_serial}' is not assigned to any vehicle",
                )

            # ── 4. Find ACTIVE trip ───────────────────────────────────────────
            try:
                trip = TollTrip.objects.select_for_update().select_related(
                    'entry_plaza', 'vehicle'
                ).get(vehicle=vehicle, status=TripStatus.ACTIVE)
            except TollTrip.DoesNotExist:
                return (
                    False,
                    STATUS_NEEDS_MANUAL_REVIEW,
                    'No active trip found in PostgreSQL',
                )

            # ── 5. Rate lookup ────────────────────────────────────────────────
            rate_obj = TollRate.objects.filter(
                entry_plaza_id=trip.entry_plaza_id,
                exit_plaza_id=exit_plaza_id,
                vehicle_type=vehicle.vehicle_type,
                effective_from__lte=dj_timezone.now().date(),
            ).order_by('-effective_from').values('rate').first()

            if rate_obj is None:
                return (
                    False,
                    STATUS_NEEDS_MANUAL_REVIEW,
                    (
                        f"No toll rate configured for "
                        f"{trip.entry_plaza_id}→{exit_plaza_id} "
                        f"vehicle_type={vehicle.vehicle_type}"
                    ),
                )

            charge: Decimal = Decimal(str(rate_obj['rate'])).quantize(Decimal('0.01'))

            # ── 6. Lock Account ───────────────────────────────────────────────
            try:
                account = Account.objects.select_for_update().get(
                    vehicle=vehicle
                )
            except Account.DoesNotExist:
                return (
                    False,
                    STATUS_NEEDS_MANUAL_REVIEW,
                    f"No account found for vehicle {vehicle.plate_number}",
                )

            # ── 7 & 8. Deduct balance (allow slight negative — log warning) ──
            balance_before: Decimal = account.balance
            account.balance -= charge
            balance_after: Decimal = account.balance

            if balance_after < Decimal('0.00'):
                logger.warning(
                    "[reconciliation] Account %s went negative after offline deduction: "
                    "balance_before=%s charge=%s balance_after=%s tag=%s",
                    account.id, balance_before, charge, balance_after, tag_serial,
                )

            # ── 9. Save account ───────────────────────────────────────────────
            account.save(update_fields=['balance', 'balance_updated_at'])

            # ── 10. Resolve exit lane (optional) ─────────────────────────────
            exit_lane = None
            if exit_lane_id:
                try:
                    exit_lane = TollLane.objects.get(id=exit_lane_id)
                except TollLane.DoesNotExist:
                    logger.warning(
                        "[reconciliation] exit_lane_id %s not found — proceeding without lane",
                        exit_lane_id,
                    )

            # ── 10. Update TollTrip ───────────────────────────────────────────
            trip.exit_plaza_id = exit_plaza_id
            trip.exit_lane = exit_lane
            trip.exit_time = exit_time
            trip.charge_amount = charge
            trip.balance_before = balance_before
            trip.balance_after = balance_after
            trip.status = TripStatus.COMPLETED
            trip.save()

            # ── 11. Create Transaction ────────────────────────────────────────
            Transaction.objects.create(
                account=account,
                toll_lane=exit_lane,
                toll_trip=trip,
                tag_serial=tag_serial,
                transaction_type=TransactionType.TOLL_DEDUCTION,
                amount=charge,
                balance_before=balance_before,
                balance_after=balance_after,
                status=TransactionStatus.SUCCESS,
                idempotency_key=idempotency_key,
                source=TransactionSource.OFFLINE_EXIT_SYNC,
            )

        logger.info(
            "[reconciliation] event %d synced — tag=%s vehicle=%s charge=%s "
            "balance_before=%s balance_after=%s trip=%s",
            event_id, tag_serial, vehicle.plate_number,
            charge, balance_before, balance_after, trip.id,
        )
        return (
            True,
            STATUS_SYNCED,
            (
                f"Synced: charge={charge} "
                f"balance_before={balance_before} "
                f"balance_after={balance_after} "
                f"trip_id={trip.id}"
            ),
        )
