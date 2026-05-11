import uuid
import logging
from decimal import Decimal
from django.db import transaction as db_transaction
from apps.vehicles.models import Tag, TagStatus
from .models import Account, Transaction, TransactionType, TransactionStatus

logger = logging.getLogger(__name__)


class TransferService:
    @staticmethod
    @db_transaction.atomic
    def execute(user, source_vehicle_id: str, target_vehicle_id: str,
                cnic: str, phone: str, name: str) -> dict:

        # ── Load accounts first so KYC verifies against the actual vehicle owner
        try:
            source_account = Account.objects.select_for_update().select_related(
                'vehicle', 'user'
            ).get(vehicle_id=source_vehicle_id)
        except Account.DoesNotExist:
            return {'success': False, 'reason': 'Source vehicle account not found', 'status_code': 404}

        try:
            target_account = Account.objects.select_for_update().select_related(
                'vehicle'
            ).get(vehicle_id=target_vehicle_id)
        except Account.DoesNotExist:
            return {'success': False, 'reason': 'Target vehicle account not found', 'status_code': 404}

        if source_account.user_id != target_account.user_id:
            return {'success': False, 'reason': 'Both vehicles must belong to the same owner', 'status_code': 403}

        # ── KYC — verify against the source vehicle's registered owner ────────
        owner = source_account.user
        stored_cnic = (owner.cnic or '').strip()
        if not stored_cnic:
            return {
                'success': False,
                'reason': 'The vehicle owner does not have a CNIC on file. Please update their profile first.',
                'status_code': 403,
            }

        phone_ok = (owner.phone or '').strip() == phone.strip()
        name_ok = (owner.full_name or '').strip().lower() == name.strip().lower()
        cnic_ok = stored_cnic.lower() == cnic.strip().lower()

        if not phone_ok:
            logger.warning("KYC phone mismatch — owner %s", owner.id)
            return {'success': False, 'reason': 'Phone number does not match the vehicle owner records', 'status_code': 403}
        if not name_ok:
            logger.warning("KYC name mismatch — owner %s", owner.id)
            return {'success': False, 'reason': 'Full name does not match the vehicle owner records', 'status_code': 403}
        if not cnic_ok:
            logger.warning("KYC CNIC mismatch — owner %s", owner.id)
            return {'success': False, 'reason': 'CNIC does not match the vehicle owner records', 'status_code': 403}

        # ── Guards ───────────────────────────────────────────────────────────
        if source_account.balance <= Decimal('0'):
            return {'success': False, 'reason': 'No balance to transfer', 'status_code': 400}

        try:
            source_tag = Tag.objects.get(vehicle=source_account.vehicle)
        except Tag.DoesNotExist:
            return {'success': False, 'reason': 'Source vehicle has no tag', 'status_code': 400}

        if source_tag.status == TagStatus.DEACTIVATED:
            return {'success': False, 'reason': 'Tag is already deactivated', 'status_code': 400}

        if source_tag.status != TagStatus.ACTIVE:
            return {'success': False, 'reason': f'Tag is {source_tag.status}', 'status_code': 400}

        # ── Transfer ─────────────────────────────────────────────────────────
        amount = source_account.balance
        reference_id = uuid.uuid4()

        src_balance_before = source_account.balance
        tgt_balance_before = target_account.balance

        source_account.balance = Decimal('0')
        target_account.balance += amount
        source_account.save(update_fields=['balance', 'balance_updated_at'])
        target_account.save(update_fields=['balance', 'balance_updated_at'])

        Transaction.objects.create(
            account=source_account,
            transaction_type=TransactionType.TRANSFER_OUT,
            amount=amount,
            balance_before=src_balance_before,
            balance_after=Decimal('0'),
            status=TransactionStatus.SUCCESS,
            reference_id=reference_id,
        )
        Transaction.objects.create(
            account=target_account,
            transaction_type=TransactionType.TRANSFER_IN,
            amount=amount,
            balance_before=tgt_balance_before,
            balance_after=target_account.balance,
            status=TransactionStatus.SUCCESS,
            reference_id=reference_id,
        )

        # ── Deactivate source tag ─────────────────────────────────────────────
        Tag.objects.filter(vehicle=source_account.vehicle).update(status=TagStatus.DEACTIVATED)

        logger.info(
            "Balance transfer — owner: %s amount: %s ref: %s src: %s dst: %s",
            owner.id, amount, reference_id,
            source_account.vehicle.plate_number,
            target_account.vehicle.plate_number,
        )
        return {
            'success': True,
            'transferred_amount': str(amount),
            'source_vehicle': source_account.vehicle.plate_number,
            'target_vehicle': target_account.vehicle.plate_number,
            'reference_id': str(reference_id),
        }
