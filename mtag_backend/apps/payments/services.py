import hashlib
import hmac
import logging
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction
from django.utils import timezone
from django.conf import settings
from apps.accounts.models import Account, Transaction, TransactionType, TransactionStatus
from .models import TopupRequest, TopupStatus

logger = logging.getLogger(__name__)


def _secure_hash(params: dict) -> str:
    """Compute JazzCash pp_SecureHash: HMAC-SHA256 over sorted non-empty values."""
    salt = settings.JAZZCASH_INTEGRITY_SALT
    sorted_values = "&".join(
        f"{k}={v}" for k, v in sorted(params.items()) if v not in (None, "")
    )
    message = f"{salt}&{sorted_values}"
    return hmac.new(
        salt.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest().upper()


class JazzCashService:
    @staticmethod
    def initiate_topup(account_id: str, user_id: int, amount: Decimal) -> dict:
        if amount < Decimal('100'):
            return {'success': False, 'reason': 'Minimum top-up amount is Rs.100'}

        topup = TopupRequest.objects.create(
            account_id=account_id,
            user_id=user_id,
            amount=amount,
        )
        logger.info("Topup initiated — id: %s amount: %s", topup.id, amount)

        return_url = f"{settings.JAZZCASH_RETURN_URL}?topup_id={topup.id}"
        payload = {
            'pp_TxnRefNo': str(topup.id).replace('-', '')[:20],
            'pp_Amount': str(int(amount * 100)),
            'pp_TxnCurrency': 'PKR',
            'pp_MerchantID': settings.JAZZCASH_MERCHANT_ID,
            'pp_Password': settings.JAZZCASH_PASSWORD,
            'pp_ReturnURL': return_url,
            'topup_id': str(topup.id),
        }
        payload['pp_SecureHash'] = _secure_hash(payload)
        return {'success': True, 'topup_id': str(topup.id), 'jazzcash_payload': payload}

    @staticmethod
    @db_transaction.atomic
    def handle_callback(jazzcash_txn_id: str, pp_response_code: str, topup_id: str) -> dict:
        if not topup_id:
            return {'success': False, 'reason': 'topup_id is required'}

        try:
            topup = TopupRequest.objects.select_for_update().get(
                id=topup_id, status=TopupStatus.PENDING
            )
        except (TopupRequest.DoesNotExist, ValidationError, ValueError):
            logger.warning("Topup not found or already processed: %s", topup_id)
            return {'success': False, 'reason': 'Topup not found or already processed'}

        topup.jazzcash_txn_id = jazzcash_txn_id

        if pp_response_code == '000':
            account = Account.objects.select_for_update().get(id=topup.account_id)
            balance_before = account.balance
            account.balance += topup.amount
            account.save(update_fields=['balance', 'balance_updated_at'])

            Transaction.objects.create(
                account=account,
                transaction_type=TransactionType.TOPUP,
                amount=topup.amount,
                balance_before=balance_before,
                balance_after=account.balance,
                status=TransactionStatus.SUCCESS,
            )

            topup.status = TopupStatus.SUCCESS
            topup.completed_at = timezone.now()
            topup.save()
            logger.info("Topup success — id: %s new_balance: %s", topup_id, account.balance)
            return {'success': True, 'new_balance': str(account.balance)}

        topup.status = TopupStatus.FAILED
        topup.save()
        logger.warning("Topup failed — id: %s code: %s", topup_id, pp_response_code)
        return {'success': False, 'reason': f'Payment failed (code: {pp_response_code})'}
