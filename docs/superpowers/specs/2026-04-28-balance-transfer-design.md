# Balance Transfer Design

## Overview

A user can transfer their full M-Tag wallet balance from one vehicle to another. Both vehicles must belong to the same user. The transfer requires KYC confirmation (CNIC, phone, name matched against the authenticated user's record). After a successful transfer the source tag is permanently deactivated and cannot be reactivated.

---

## Data Model Changes

### `apps/accounts/models.py`

Add two new `TransactionType` choices:

```python
TRANSFER_OUT = 'transfer_out', 'Transfer Out'
TRANSFER_IN  = 'transfer_in',  'Transfer In'
```

Add a `reference_id` field to `Transaction` to pair the two sides of a transfer:

```python
reference_id = models.UUIDField(null=True, blank=True, db_index=True)
```

### `apps/vehicles/models.py`

Add a new `TagStatus` choice to mark a tag permanently retired via transfer:

```python
DEACTIVATED = 'deactivated', 'Deactivated'
```

This is distinct from:
- `suspended` — temporary block
- `expired` — date-based expiry
- `deactivated` — permanent, caused only by a balance transfer

---

## API

### Endpoint

`POST /api/v1/accounts/transfer/`

**Auth:** `IsAuthenticated` (any logged-in user)

### Request Body

```json
{
  "source_vehicle_id": "<uuid>",
  "target_vehicle_id": "<uuid>",
  "cnic":  "12345-1234567-1",
  "phone": "03001234567",
  "name":  "Ali Hassan"
}
```

### Success Response — HTTP 200

```json
{
  "success": true,
  "data": {
    "transferred_amount": "1250.00",
    "source_vehicle":     "ABC-123",
    "target_vehicle":     "XYZ-999",
    "reference_id":       "<uuid>"
  },
  "message": "Balance transferred successfully"
}
```

---

## Service Logic — `TransferService.execute()`

Runs inside a single `db_transaction.atomic()` block.

1. **KYC** — compare submitted `cnic`, `phone`, `name` (case-insensitive strip) against `request.user.cnic`, `request.user.phone`, `request.user.full_name`. Reject with 403 if any field does not match.
2. **Load accounts** — fetch source and target `Account` with `select_for_update()`. Both must have `vehicle.owner == request.user`, else 403.
3. **Same-vehicle guard** — source and target vehicle IDs must differ, else 400.
4. **Balance guard** — `source_account.balance > 0`, else 400.
5. **Tag guard** — source tag `status == active`, else 400.
6. **Execute transfer:**
   - `reference_id = uuid4()`
   - `amount = source_account.balance`
   - `target_account.balance += amount`
   - `source_account.balance = 0`
   - Save both accounts.
7. **Write transactions** — two `Transaction` records sharing the same `reference_id`:
   - `transfer_out` on source account (`amount`, `balance_before`, `balance_after=0`)
   - `transfer_in` on target account (`amount`, `balance_before`, `balance_after`)
8. **Deactivate source tag** — `Tag.objects.filter(vehicle=source_vehicle).update(status='deactivated')`

---

## Error Cases

| Condition | HTTP | Message |
|---|---|---|
| KYC fields don't match | 403 | "Identity verification failed" |
| Source vehicle not owned by user | 403 | "Vehicle does not belong to your account" |
| Target vehicle not owned by user | 403 | "Vehicle does not belong to your account" |
| Source and target are the same | 400 | "Source and target vehicle must be different" |
| Source balance is zero | 400 | "No balance to transfer" |
| Source tag already deactivated | 400 | "Tag is already deactivated" |

---

## Files Touched

| File | Change |
|---|---|
| `apps/accounts/models.py` | Add `TRANSFER_OUT`, `TRANSFER_IN` to `TransactionType`; add `reference_id` to `Transaction` |
| `apps/accounts/serializers.py` | Add `TransferSerializer` (validates request body) |
| `apps/accounts/services.py` | New file — `TransferService.execute()` |
| `apps/accounts/views.py` | Add `TransferView` |
| `apps/accounts/urls.py` | Wire `transfer/` URL |
| `apps/vehicles/models.py` | Add `DEACTIVATED` to `TagStatus` |
| DB migration | `apps/accounts/migrations/` — adds `reference_id` column |
| DB migration | `apps/vehicles/migrations/` — adds `deactivated` choice (no schema change, choices are app-level) |
