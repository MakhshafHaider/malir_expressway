import uuid
from django.db import models


class TopupStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    SUCCESS = 'success', 'Success'
    FAILED = 'failed', 'Failed'


class TopupRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey('accounts.Account', on_delete=models.CASCADE, related_name='topups')
    user = models.ForeignKey('users.User', on_delete=models.CASCADE, related_name='topups')
    jazzcash_txn_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=TopupStatus.choices, default=TopupStatus.PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'topup_requests'
        ordering = ['-requested_at']

    def __str__(self):
        return f"Topup Rs.{self.amount} — {self.status}"
