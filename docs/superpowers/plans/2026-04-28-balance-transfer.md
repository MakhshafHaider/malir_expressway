# Balance Transfer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user transfer their full M-Tag wallet balance from one of their vehicles to another, with KYC confirmation, permanently deactivating the source tag.

**Architecture:** A single `POST /api/v1/accounts/transfer/` endpoint delegates entirely to `TransferService.execute()` which runs atomically — KYC check, balance move, two transaction records, tag deactivation — all in one DB transaction. No new model is required; `Transaction` gains a `reference_id` UUID field to pair the two sides of a transfer.

**Tech Stack:** Django 4.x, Django REST Framework, SimpleJWT, PostgreSQL, `django.db.transaction.atomic`.

**Venv python path:** `/home/makhshaf-haider/Downloads/m tag/mtag_backend/venv/bin/python3`  
**Working directory for all commands:** `/home/makhshaf-haider/Downloads/m tag/mtag_backend`  
**Settings module:** `config.settings.local`

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `apps/accounts/models.py` | Modify | Add `TRANSFER_OUT`/`TRANSFER_IN` to `TransactionType`; add `reference_id` to `Transaction` |
| `apps/vehicles/models.py` | Modify | Add `DEACTIVATED` to `TagStatus` |
| `apps/accounts/migrations/000X_add_transfer_fields.py` | Create (auto) | Migration for `reference_id` column |
| `apps/accounts/serializers.py` | Modify | Add `TransferSerializer` |
| `apps/accounts/services.py` | Create | `TransferService.execute()` — all business logic |
| `apps/accounts/views.py` | Modify | Add `TransferView` |
| `apps/accounts/urls.py` | Modify | Wire `transfer/` URL |

---

## Task 1: Update Models

**Files:**
- Modify: `apps/accounts/models.py`
- Modify: `apps/vehicles/models.py`

- [ ] **Step 1: Add `TRANSFER_OUT` and `TRANSFER_IN` to `TransactionType`, and `reference_id` to `Transaction` in `apps/accounts/models.py`**

Replace the file contents with:

```python
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
    processed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'transactions'
        indexes = [models.Index(fields=['processed_at'])]
        ordering = ['-processed_at']

    def __str__(self):
        return f"{self.transaction_type} Rs.{self.amount} — {self.account}"
```

- [ ] **Step 2: Add `DEACTIVATED` to `TagStatus` in `apps/vehicles/models.py`**

Replace only the `TagStatus` class (lines 18–21) with:

```python
class TagStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    EXPIRED = 'expired', 'Expired'
    SUSPENDED = 'suspended', 'Suspended'
    DEACTIVATED = 'deactivated', 'Deactivated'
```

- [ ] **Step 3: Generate and apply the migration**

```bash
cd "/home/makhshaf-haider/Downloads/m tag/mtag_backend"
DJANGO_SETTINGS_MODULE=config.settings.local \
  "/home/makhshaf-haider/Downloads/m tag/mtag_backend/venv/bin/python3" \
  manage.py makemigrations accounts --name add_transfer_fields
```

Expected output: `Migrations for 'accounts': apps/accounts/migrations/0003_add_transfer_fields.py`

```bash
DJANGO_SETTINGS_MODULE=config.settings.local \
  "/home/makhshaf-haider/Downloads/m tag/mtag_backend/venv/bin/python3" \
  manage.py migrate --settings=config.settings.local
```

Expected output: `Applying accounts.0003_add_transfer_fields... OK`

- [ ] **Step 4: Verify Django system check passes**

```bash
DJANGO_SETTINGS_MODULE=config.settings.local \
  "/home/makhshaf-haider/Downloads/m tag/mtag_backend/venv/bin/python3" \
  manage.py check
```

Expected: `System check identified no issues (0 silenced).`

---

## Task 2: Add `TransferSerializer`

**Files:**
- Modify: `apps/accounts/serializers.py`

- [ ] **Step 1: Append `TransferSerializer` to `apps/accounts/serializers.py`**

Add at the end of the file:

```python
from apps.vehicles.models import Vehicle


class TransferSerializer(serializers.Serializer):
    source_vehicle_id = serializers.UUIDField()
    target_vehicle_id = serializers.UUIDField()
    cnic = serializers.CharField(max_length=20)
    phone = serializers.CharField(max_length=20)
    name = serializers.CharField(max_length=100)

    def validate(self, data):
        if data['source_vehicle_id'] == data['target_vehicle_id']:
            raise serializers.ValidationError("Source and target vehicle must be different.")
        return data
```

- [ ] **Step 2: Verify no import errors**

```bash
DJANGO_SETTINGS_MODULE=config.settings.local \
  "/home/makhshaf-haider/Downloads/m tag/mtag_backend/venv/bin/python3" \
  -c "from apps.accounts.serializers import TransferSerializer; print('OK')"
```

Expected: `OK`

---

## Task 3: Create `TransferService`

**Files:**
- Create: `apps/accounts/services.py`

- [ ] **Step 1: Create `apps/accounts/services.py` with the following content**

```python
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

        # ── KYC ──────────────────────────────────────────────────────────────
        if (
            (user.cnic or '').strip().lower() != cnic.strip().lower() or
            (user.phone or '').strip() != phone.strip() or
            (user.full_name or '').strip().lower() != name.strip().lower()
        ):
            logger.warning("KYC failed for user %s", user.id)
            return {'success': False, 'reason': 'Identity verification failed', 'status_code': 403}

        # ── Load accounts ────────────────────────────────────────────────────
        try:
            source_account = Account.objects.select_for_update().select_related(
                'vehicle__tag'
            ).get(vehicle_id=source_vehicle_id)
        except Account.DoesNotExist:
            return {'success': False, 'reason': 'Source vehicle account not found', 'status_code': 404}

        if source_account.user_id != user.id:
            return {'success': False, 'reason': 'Vehicle does not belong to your account', 'status_code': 403}

        try:
            target_account = Account.objects.select_for_update().select_related(
                'vehicle'
            ).get(vehicle_id=target_vehicle_id)
        except Account.DoesNotExist:
            return {'success': False, 'reason': 'Target vehicle account not found', 'status_code': 404}

        if target_account.user_id != user.id:
            return {'success': False, 'reason': 'Vehicle does not belong to your account', 'status_code': 403}

        # ── Guards ───────────────────────────────────────────────────────────
        if source_account.balance <= Decimal('0'):
            return {'success': False, 'reason': 'No balance to transfer', 'status_code': 400}

        try:
            source_tag = source_account.vehicle.tag
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
            "Balance transfer — user: %s amount: %s ref: %s src: %s dst: %s",
            user.id, amount, reference_id,
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
```

- [ ] **Step 2: Verify no import errors**

```bash
DJANGO_SETTINGS_MODULE=config.settings.local \
  "/home/makhshaf-haider/Downloads/m tag/mtag_backend/venv/bin/python3" \
  -c "from apps.accounts.services import TransferService; print('OK')"
```

Expected: `OK`

---

## Task 4: Add `TransferView`

**Files:**
- Modify: `apps/accounts/views.py`

- [ ] **Step 1: Add the import and `TransferView` to `apps/accounts/views.py`**

Add this import at the top of the file (after existing imports):

```python
from .services import TransferService
from .serializers import AccountSerializer, TransactionSerializer, TransferSerializer
```

Then append `TransferView` at the end of the file:

```python
class TransferView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TransferSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Invalid data", errors=serializer.errors)

        d = serializer.validated_data
        result = TransferService.execute(
            user=request.user,
            source_vehicle_id=str(d['source_vehicle_id']),
            target_vehicle_id=str(d['target_vehicle_id']),
            cnic=d['cnic'],
            phone=d['phone'],
            name=d['name'],
        )

        if not result['success']:
            return error_response(
                result['reason'],
                status_code=result.get('status_code', 400)
            )
        return success_response(data=result, message="Balance transferred successfully")
```

- [ ] **Step 2: Verify no import errors**

```bash
DJANGO_SETTINGS_MODULE=config.settings.local \
  "/home/makhshaf-haider/Downloads/m tag/mtag_backend/venv/bin/python3" \
  -c "from apps.accounts.views import TransferView; print('OK')"
```

Expected: `OK`

---

## Task 5: Wire URL

**Files:**
- Modify: `apps/accounts/urls.py`

- [ ] **Step 1: Replace `apps/accounts/urls.py` with**

```python
from django.urls import path
from .views import AccountDetailView, TransactionListView, AdminAccountListView, TransferView

urlpatterns = [
    path('vehicle/<uuid:vehicle_id>/', AccountDetailView.as_view(), name='account-detail'),
    path('<uuid:account_id>/transactions/', TransactionListView.as_view(), name='transaction-list'),
    path('admin/all/', AdminAccountListView.as_view(), name='admin-accounts'),
    path('transfer/', TransferView.as_view(), name='balance-transfer'),
]
```

- [ ] **Step 2: Verify the route resolves**

```bash
DJANGO_SETTINGS_MODULE=config.settings.local \
  "/home/makhshaf-haider/Downloads/m tag/mtag_backend/venv/bin/python3" \
  manage.py shell -c "
from django.urls import reverse
print(reverse('balance-transfer'))
"
```

Expected: `/api/v1/accounts/transfer/`

- [ ] **Step 3: Final Django system check**

```bash
DJANGO_SETTINGS_MODULE=config.settings.local \
  "/home/makhshaf-haider/Downloads/m tag/mtag_backend/venv/bin/python3" \
  manage.py check
```

Expected: `System check identified no issues (0 silenced).`

---

## Spec Coverage Checklist

| Requirement | Covered in |
|---|---|
| KYC — CNIC, phone, name matched against user record | Task 3 — `TransferService.execute()` KYC block |
| Both vehicles must belong to same user | Task 3 — `user_id` ownership checks |
| Full balance transferred (no partial) | Task 3 — `amount = source_account.balance` |
| Source balance must be > 0 | Task 3 — balance guard |
| Source tag must be active | Task 3 — tag status guard |
| Source tag already deactivated → 400 | Task 3 — explicit `DEACTIVATED` check |
| `DEACTIVATED` tag status added | Task 1 — `TagStatus` |
| `TRANSFER_OUT` / `TRANSFER_IN` transaction types | Task 1 — `TransactionType` |
| `reference_id` links both transaction records | Task 1 model + Task 3 service |
| Migration for `reference_id` column | Task 1 Step 3 |
| `TransferSerializer` validates same-vehicle | Task 2 |
| `POST /api/v1/accounts/transfer/` endpoint | Task 4 + Task 5 |
| All 6 error cases return correct HTTP codes | Task 3 — `status_code` in each return dict |
