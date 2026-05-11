import logging
import threading
import time
from decimal import Decimal
from django.db import transaction as db_transaction
from django.utils import timezone
from apps.vehicles.models import Tag, TagStatus
from apps.accounts.models import Account, Transaction, TransactionType, TransactionStatus
from .models import TollTrip, TollRate, TollLane, TripStatus

logger = logging.getLogger(__name__)

MINIMUM_BALANCE = Decimal('50.00')

# ── In-memory rate cache ──────────────────────────────────────────────────────
# Toll rates change rarely (admin action). Cache them for 10 minutes so every
# exit does not hit the database for the same rate lookup.
_rate_cache: dict = {}
_RATE_CACHE_TTL = 600  # seconds


def _cached_rate(entry_plaza_id, exit_plaza_id, vehicle_type):
    key = f"{entry_plaza_id}:{exit_plaza_id}:{vehicle_type}"
    entry = _rate_cache.get(key)
    if entry:
        rate_val, ts = entry
        if time.monotonic() - ts < _RATE_CACHE_TTL:
            return rate_val
    # Cache miss — query DB and store result
    rate_obj = TollRate.objects.filter(
        entry_plaza_id=entry_plaza_id,
        exit_plaza_id=exit_plaza_id,
        vehicle_type=vehicle_type,
        effective_from__lte=timezone.now().date(),
    ).order_by('-effective_from').values('rate').first()
    if rate_obj:
        _rate_cache[key] = (rate_obj['rate'], time.monotonic())
        return rate_obj['rate']
    return None


def invalidate_rate_cache():
    """Call after any admin creates or updates a toll rate."""
    _rate_cache.clear()
    logger.info("Toll rate cache cleared")


def _bg(fn, *args, **kwargs):
    """Fire-and-forget background thread for non-critical DB writes."""
    threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()


def _update_last_scanned(tag_id):
    try:
        Tag.objects.filter(id=tag_id).update(last_scanned_at=timezone.now())
    except Exception as exc:
        logger.warning("last_scanned_at update failed: %s", exc)


# ── Entry ─────────────────────────────────────────────────────────────────────

class EntryService:
    @staticmethod
    @db_transaction.atomic
    def process_entry(tag_serial: str, plaza_id: str, lane_id: str = None) -> dict:
        logger.info("Entry — tag: %s plaza: %s", tag_serial, plaza_id)

        # 1. Verify tag + vehicle (single query via select_related)
        try:
            tag = Tag.objects.select_related('vehicle').get(tag_serial=tag_serial)
        except Tag.DoesNotExist:
            return {'success': False, 'reason': 'Tag not found'}

        if not tag.is_valid:
            if tag.vehicle_id is None:
                return {'success': False, 'reason': 'Tag not assigned to any vehicle'}
            if tag.status != TagStatus.ACTIVE:
                return {'success': False, 'reason': f'Tag is {tag.status}'}
            return {'success': False, 'reason': 'Tag expired'}

        vehicle = tag.vehicle
        if vehicle.status != 'active':
            return {'success': False, 'reason': f'Vehicle is {vehicle.status}'}

        # 2. Lock account and check minimum balance
        try:
            account = Account.objects.select_for_update().get(vehicle=vehicle)
        except Account.DoesNotExist:
            return {'success': False, 'reason': 'No account found for this vehicle'}

        if account.balance < MINIMUM_BALANCE:
            return {
                'success': False,
                'reason': 'Insufficient balance',
                'current_balance': str(account.balance),
                'minimum_required': str(MINIMUM_BALANCE),
            }

        # 3. Prevent duplicate active trip
        if TollTrip.objects.filter(vehicle=vehicle, status=TripStatus.ACTIVE).exists():
            return {'success': False, 'reason': 'Vehicle already has an active trip'}

        # 4. Resolve lane (optional — failure is non-fatal)
        lane = None
        if lane_id:
            try:
                lane = TollLane.objects.get(id=lane_id, is_active=True)
            except TollLane.DoesNotExist:
                pass

        # 5. Create trip record
        trip = TollTrip.objects.create(
            vehicle=vehicle,
            tag=tag,
            account=account,
            entry_plaza_id=plaza_id,
            entry_lane=lane,
            status=TripStatus.ACTIVE,
        )

        # last_scanned_at is not gate-critical — update after response
        _bg(_update_last_scanned, tag.id)

        logger.info("Entry OK — trip: %s vehicle: %s", trip.id, vehicle.plate_number)
        return {
            'success': True,
            'trip_id': str(trip.id),
            'vehicle': vehicle.plate_number,
            'vehicle_type': vehicle.vehicle_type,
            'current_balance': str(account.balance),
            'entry_time': trip.entry_time.isoformat(),
        }


# ── Exit helpers ──────────────────────────────────────────────────────────────

def _find_active_trip(vehicle):
    """
    Find active trip for vehicle.

    Lookup order:
      1. Local DB (default connection) — fast, covers 99% of cases.
         Sync agent pulls all active trips from master every 30s,
         so a vehicle that entered at another plaza will already be here.
      2. Master DB (explicit master_pg) — fallback for the edge case where
         the vehicle drove between plazas faster than the 30-second sync window.
    """
    from django.db import connections

    trip = TollTrip.objects.select_related('entry_plaza', 'vehicle').filter(
        vehicle=vehicle, status=TripStatus.ACTIVE
    ).first()
    if trip:
        return trip

    try:
        with connections['master_pg'].cursor() as cur:
            cur.execute("""
                SELECT id FROM toll_trips
                WHERE vehicle_id = %s AND status = 'active'
                LIMIT 1
            """, [str(vehicle.id)])
            row = cur.fetchone()
            if row:
                return TollTrip.objects.select_related(
                    'entry_plaza', 'vehicle'
                ).filter(id=row[0]).first()
    except Exception as exc:
        logger.warning("Master fallback trip lookup failed: %s", exc)

    return None


# ── Exit ──────────────────────────────────────────────────────────────────────

class ExitService:
    @staticmethod
    @db_transaction.atomic
    def process_exit(tag_serial: str, exit_plaza_id: str, lane_id: str = None) -> dict:
        logger.info("Exit — tag: %s plaza: %s", tag_serial, exit_plaza_id)

        # 1. Verify tag + vehicle
        try:
            tag = Tag.objects.select_related('vehicle').get(tag_serial=tag_serial)
        except Tag.DoesNotExist:
            return {'success': False, 'reason': 'Tag not found'}

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

        # 3. Rate lookup — served from cache on warm requests
        rate = _cached_rate(
            str(trip.entry_plaza_id), exit_plaza_id, trip.vehicle.vehicle_type
        )
        if rate is None:
            logger.error(
                "No toll rate: %s→%s %s",
                trip.entry_plaza_id, exit_plaza_id, trip.vehicle.vehicle_type,
            )
            return {'success': False, 'reason': 'Toll rate not configured for this route'}

        charge = Decimal(str(rate)).quantize(Decimal('0.01'))

        # 4. Lock account and check balance
        account = Account.objects.select_for_update().get(id=trip.account_id)
        if account.balance < charge:
            return {
                'success': False,
                'reason': 'Insufficient balance at exit',
                'charge': str(charge),
                'current_balance': str(account.balance),
            }

        # 5. Deduct balance
        now = timezone.now()
        balance_before = account.balance
        account.balance -= charge
        account.save(update_fields=['balance', 'balance_updated_at'])

        # 6. Resolve lane (optional)
        lane = None
        if lane_id:
            try:
                lane = TollLane.objects.get(id=lane_id, is_active=True)
            except TollLane.DoesNotExist:
                pass

        # 7. Close trip
        trip.exit_plaza_id = exit_plaza_id
        trip.exit_lane = lane
        trip.exit_time = now
        trip.charge_amount = charge
        trip.balance_before = balance_before
        trip.balance_after = account.balance
        trip.status = TripStatus.COMPLETED
        trip.save()

        # 8. Audit transaction record
        Transaction.objects.create(
            account=account,
            toll_lane=lane,
            toll_trip=trip,
            tag_serial=tag_serial,
            transaction_type=TransactionType.TOLL_DEDUCTION,
            amount=charge,
            balance_before=balance_before,
            balance_after=account.balance,
            status=TransactionStatus.SUCCESS,
        )

        # last_scanned_at is not gate-critical — update after response
        _bg(_update_last_scanned, tag.id)

        logger.info("Exit OK — trip: %s charge: %s balance: %s", trip.id, charge, account.balance)
        return {
            'success': True,
            'trip_id': str(trip.id),
            'vehicle': trip.vehicle.plate_number,
            'entry_plaza': trip.entry_plaza.name,
            'exit_plaza_id': exit_plaza_id,
            'charge': str(charge),
            'balance_remaining': str(account.balance),
            'entry_time': trip.entry_time.isoformat(),
            'exit_time': now.isoformat(),
        }
