import uuid
from django.db import models


class TransactionType(models.TextChoices):
    TOLL_DEDUCTION = 'toll_deduction', 'Toll Deduction'
    TOPUP = 'topup', 'Top-up'
    REFUND = 'refund', 'Refund'
    TRANSFER_OUT = 'transfer_out', 'Transfer Out'
    TRANSFER_IN = 'transfer_in', 'Transfer In'


class TransactionStatus(models.TextChoices):
    SUCCESS = 'success', 'Success'
    FAILED = 'failed', 'Failed'
    PENDING = 'pending', 'Pending'


class TransactionSource(models.TextChoices):
    ONLINE_EXIT = 'online_exit', 'Online Exit'
    OFFLINE_EXIT_SYNC = 'offline_exit_sync', 'Offline Exit (Synced)'
    TOPUP_JAZZCASH = 'topup_jazzcash', 'Top-up JazzCash'
    TOPUP_CASH = 'topup_cash', 'Top-up Cash'
    REFUND = 'refund', 'Refund'


class Account(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vehicle = models.OneToOneField('vehicles.Vehicle', on_delete=models.CASCADE, related_name='account')
    user = models.ForeignKey('users.User', on_delete=models.CASCADE, related_name='accounts')
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    balance_updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'accounts'

    def __str__(self):
        return f"{self.vehicle.plate_number} — Rs.{self.balance}"


class Transaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='transactions')
    toll_lane = models.ForeignKey(
        'tolls.TollLane', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='transactions'
    )
    toll_trip = models.ForeignKey(
        'tolls.TollTrip', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='transactions'
    )
    tag_serial = models.CharField(max_length=24, blank=True)
    transaction_type = models.CharField(max_length=30, choices=TransactionType.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    balance_before = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=TransactionStatus.choices, default=TransactionStatus.SUCCESS)
    reference_id = models.UUIDField(null=True, blank=True, db_index=True)
    idempotency_key = models.CharField(max_length=64, unique=True, null=True, blank=True, db_index=True)
    source = models.CharField(max_length=30, choices=TransactionSource.choices, null=True, blank=True)
    processed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'transactions'
        indexes = [models.Index(fields=['processed_at'])]
        ordering = ['-processed_at']

    def __str__(self):
        return f"{self.transaction_type} Rs.{self.amount} — {self.account}"
