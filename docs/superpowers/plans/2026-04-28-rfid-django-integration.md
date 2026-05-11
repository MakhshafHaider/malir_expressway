# RFID-Django Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate `rfid_final.py` with the Django REST backend so the physical toll gate calls the API for entry/exit, and fix the two broken Django features (JazzCash HMAC signature, tag reissue endpoint).

**Architecture:** The RFID script reads a tag TID, determines whether it is at an entry or exit gate (set by a config flag), then calls `POST /api/v1/tolls/entry/` or `POST /api/v1/tolls/exit/` using a pre-configured operator JWT token. The script still owns the serial port (barrier) and the local display URLs — Django owns business logic, balance, and trip records. Two independent Django fixes (JazzCash HMAC, tag reissue) are done first because they are self-contained.

**Tech Stack:** Python 3, Django REST Framework, SimpleJWT, `requests`, `pyserial`, `hmac`/`hashlib` (stdlib), PostgreSQL via Django ORM.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `rfid_final.py` | **Rewrite** | Call Django API instead of direct DB; entry/exit mode; barrier + display unchanged |
| `rfid_config.ini` | **Create** | Gate-local settings (API URL, plaza_id, lane_id, gate_mode, operator token) |
| `mtag_backend/apps/payments/services.py` | **Modify** | Add HMAC-SHA256 `pp_SecureHash` to JazzCash payload |
| `mtag_backend/apps/vehicles/views.py` | **Modify** | Add `TagReissueView` |
| `mtag_backend/apps/vehicles/serializers.py` | **Modify** | Add `TagReissueSerializer` |
| `mtag_backend/apps/vehicles/urls.py` | **Modify** | Wire `tags/<uuid:vehicle_id>/reissue/` URL |

---

## Task 1: Fix JazzCash HMAC-SHA256 Signature

JazzCash rejects any payment where `pp_SecureHash` is missing. The hash is computed as
`HMAC-SHA256(IntegritySalt, "&".join(f"{k}={v}" for k,v in sorted_non_empty_params))`.

**Files:**
- Modify: `mtag_backend/apps/payments/services.py`

- [ ] **Step 1: Open and read the current file**

  Current `initiate_topup` builds `payload` but never adds `pp_SecureHash`. We will add a private helper `_secure_hash(params: dict) -> str` and call it.

- [ ] **Step 2: Replace `initiate_topup` in `mtag_backend/apps/payments/services.py`**

```python
import hashlib
import hmac
import logging
from decimal import Decimal
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

        payload = {
            'pp_TxnRefNo': str(topup.id).replace('-', '')[:20],
            'pp_Amount': str(int(amount * 100)),
            'pp_TxnCurrency': 'PKR',
            'pp_MerchantID': settings.JAZZCASH_MERCHANT_ID,
            'pp_Password': settings.JAZZCASH_PASSWORD,
            'pp_ReturnURL': settings.JAZZCASH_RETURN_URL,
            'topup_id': str(topup.id),
        }
        payload['pp_SecureHash'] = _secure_hash(payload)
        return {'success': True, 'topup_id': str(topup.id), 'jazzcash_payload': payload}

    @staticmethod
    @db_transaction.atomic
    def handle_callback(jazzcash_txn_id: str, pp_response_code: str, topup_id: str) -> dict:
        try:
            topup = TopupRequest.objects.select_for_update().get(
                id=topup_id, status=TopupStatus.PENDING
            )
        except TopupRequest.DoesNotExist:
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
```

- [ ] **Step 3: Verify Django starts without import errors**

```bash
cd "/home/makhshaf-haider/Downloads/m tag/mtag_backend"
python manage.py check --settings=config.settings.local 2>&1 | head -20
```

Expected: `System check identified no issues (0 silenced).`

---

## Task 2: Add Tag Reissue Endpoint

When a tag expires or is lost, the operator needs to assign a new physical RFID tag to an existing vehicle without re-registering the vehicle.

**Endpoint:** `POST /api/v1/vehicles/tags/<uuid:vehicle_id>/reissue/`  
**Auth:** Operator only  
**Body:** `{ "tag_serial": "AABBCCDD...", "expiry_date": "2027-12-31" }`  
**Behaviour:** Deactivate the old tag (set status=`expired`), create a new `Tag` linked to the same vehicle.

**Files:**
- Modify: `mtag_backend/apps/vehicles/serializers.py`
- Modify: `mtag_backend/apps/vehicles/views.py`
- Modify: `mtag_backend/apps/vehicles/urls.py`

- [ ] **Step 1: Add `TagReissueSerializer` to `mtag_backend/apps/vehicles/serializers.py`**

  Append after the existing `VehicleCreateSerializer` class:

```python
class TagReissueSerializer(serializers.Serializer):
    tag_serial = serializers.CharField(max_length=24)
    expiry_date = serializers.DateField()

    def validate_tag_serial(self, value):
        if Tag.objects.filter(tag_serial=value).exists():
            raise serializers.ValidationError("Tag serial already in use.")
        return value
```

- [ ] **Step 2: Add `TagReissueView` to `mtag_backend/apps/vehicles/views.py`**

  Append after `VehicleByPlateView`:

```python
from django.utils import timezone
from .models import Tag, TagStatus


class TagReissueView(APIView):
    permission_classes = [IsOperator]

    def post(self, request, vehicle_id):
        try:
            vehicle = Vehicle.objects.get(pk=vehicle_id)
        except Vehicle.DoesNotExist:
            return error_response("Vehicle not found", status_code=404)

        from .serializers import TagReissueSerializer
        serializer = TagReissueSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Invalid data", errors=serializer.errors)

        # expire old tag if present
        Tag.objects.filter(vehicle=vehicle).update(status=TagStatus.EXPIRED)

        new_tag = Tag.objects.create(
            vehicle=vehicle,
            tag_serial=serializer.validated_data['tag_serial'],
            expiry_date=serializer.validated_data['expiry_date'],
        )
        logger.info("Tag reissued for vehicle %s — new serial %s", vehicle.plate_number, new_tag.tag_serial)
        return success_response(
            data=TagSerializer(new_tag).data,
            message="Tag reissued successfully",
            status_code=201,
        )
```

- [ ] **Step 3: Wire URL in `mtag_backend/apps/vehicles/urls.py`**

  Replace file contents:

```python
from django.urls import path
from .views import VehicleListCreateView, VehicleDetailView, VehicleByPlateView, TagReissueView

urlpatterns = [
    path('', VehicleListCreateView.as_view(), name='vehicle-list'),
    path('<uuid:pk>/', VehicleDetailView.as_view(), name='vehicle-detail'),
    path('plate/<str:plate_number>/', VehicleByPlateView.as_view(), name='vehicle-by-plate'),
    path('tags/<uuid:vehicle_id>/reissue/', TagReissueView.as_view(), name='tag-reissue'),
]
```

- [ ] **Step 4: Verify Django routes are registered**

```bash
cd "/home/makhshaf-haider/Downloads/m tag/mtag_backend"
python manage.py show_urls --settings=config.settings.local 2>/dev/null | grep reissue
# if show_urls not available:
python manage.py shell --settings=config.settings.local -c "
from django.urls import reverse
print(reverse('tag-reissue', kwargs={'vehicle_id': '00000000-0000-0000-0000-000000000000'}))
"
```

Expected output: `/api/v1/vehicles/tags/00000000-0000-0000-0000-000000000000/reissue/`

- [ ] **Step 5: Verify Django still starts clean**

```bash
python manage.py check --settings=config.settings.local 2>&1 | head -5
```

Expected: `System check identified no issues (0 silenced).`

---

## Task 3: Create Gate Config File

Each physical toll gate machine needs its own local config that tells the RFID script which plaza/lane it is and whether it is an entry or exit gate.

**Files:**
- Create: `rfid_config.ini` (sits next to `rfid_final.py`)

- [ ] **Step 1: Create `rfid_config.ini`**

```ini
[gate]
; "entry" or "exit"
mode = entry

; UUID of this plaza from the Django admin / GET /api/v1/tolls/plazas/
plaza_id = 00000000-0000-0000-0000-000000000000

; UUID of this lane (optional — leave blank if unknown)
lane_id =

[api]
; Base URL of the Django backend reachable from this machine
base_url = http://192.168.78.8:8000

; JWT token for an operator account — obtain via POST /api/v1/auth/login/
; Rotate this token periodically using the login endpoint
operator_token = PASTE_OPERATOR_JWT_HERE

[display]
; Local display device IP (same as before)
display_ip = 192.168.78.12

[barrier]
; Serial port for barrier controller
port = /dev/ttyUSB0
baudrate = 115200
; Seconds the barrier stays open
open_seconds = 2.0

[scanner]
; RFID reader TCP address
reader_host = 192.168.78.8
reader_port = 9090
; Seconds to wait before re-scanning the same tag
tag_cooldown = 5.0
```

---

## Task 4: Rewrite `rfid_final.py` to Use Django API

**Files:**
- Rewrite: `rfid_final.py`

The script keeps: serial barrier control, display HTTP calls, RFID reader loop.  
The script removes: direct psycopg2 connection, `get_tag_record`, `get_fare_price`, `update_balance`.  
The script adds: `ApiClient` that calls `/api/v1/tolls/entry/` or `/api/v1/tolls/exit/`, reads gate mode from config.

- [ ] **Step 1: Overwrite `rfid_final.py` with the following**

```python
import configparser
import time
import threading
import requests
import serial
from datetime import datetime
from com.rfid.helper import *
from com.rfid.enumeration import *
from com.rfid.Reader import *
from com.rfid.models import *
from com.rfid.interface import *

# ── Config ──────────────────────────────────────────────────────────────────
_cfg = configparser.ConfigParser()
_cfg.read('rfid_config.ini')

GATE_MODE    = _cfg.get('gate', 'mode', fallback='entry').strip().lower()   # "entry" or "exit"
PLAZA_ID     = _cfg.get('gate', 'plaza_id', fallback='').strip()
LANE_ID      = _cfg.get('gate', 'lane_id', fallback='').strip() or None

API_BASE     = _cfg.get('api', 'base_url', fallback='http://localhost:8000').rstrip('/')
OPERATOR_TOKEN = _cfg.get('api', 'operator_token', fallback='').strip()

DISPLAY_IP   = _cfg.get('display', 'display_ip', fallback='192.168.78.72')
SERIAL_PORT  = _cfg.get('barrier', 'port', fallback='/dev/ttyUSB0')
SERIAL_BAUD  = int(_cfg.get('barrier', 'baudrate', fallback='115200'))
OPEN_SECONDS = float(_cfg.get('barrier', 'open_seconds', fallback='2.0'))
TAG_COOLDOWN = float(_cfg.get('scanner', 'tag_cooldown', fallback='5.0'))
READER_HOST  = _cfg.get('scanner', 'reader_host', fallback='192.168.78.68')
READER_PORT  = int(_cfg.get('scanner', 'reader_port', fallback='9090'))

ENTRY_URL    = f"{API_BASE}/api/v1/tolls/entry/"
EXIT_URL     = f"{API_BASE}/api/v1/tolls/exit/"
FARE_DISPLAY = f"http://{DISPLAY_IP}/?vehicle_number=Q.TAG&fare_amount={{fare}}"
THANKYOU_URL = f"http://{DISPLAY_IP}/thankyou"
WELCOME_URL  = f"http://{DISPLAY_IP}/?vehicle_number=WELCOME&take_slip"
# ────────────────────────────────────────────────────────────────────────────


def normalize_tid(tid: str) -> str:
    return tid.replace(" ", "").upper() if tid else ""


class ApiClient:
    """Thin wrapper around the Django toll entry/exit endpoints."""

    _headers = {
        'Authorization': f'Bearer {OPERATOR_TOKEN}',
        'Content-Type': 'application/json',
    }

    @classmethod
    def process_tag(cls, tag_serial: str) -> dict:
        """
        Call the correct endpoint based on GATE_MODE.
        Returns the parsed JSON body from Django on success,
        or a dict with 'success': False and 'reason' on failure.
        """
        payload = {
            'tag_serial': tag_serial,
            'plaza_id': PLAZA_ID,
        }
        if LANE_ID:
            payload['lane_id'] = LANE_ID

        url = ENTRY_URL if GATE_MODE == 'entry' else EXIT_URL
        try:
            resp = requests.post(url, json=payload, headers=cls._headers, timeout=5)
            body = resp.json()
            if resp.status_code == 200 and body.get('success'):
                return body
            reason = body.get('message') or body.get('reason') or f'HTTP {resp.status_code}'
            return {'success': False, 'reason': reason}
        except requests.RequestException as exc:
            return {'success': False, 'reason': f'API unreachable: {exc}'}


class RfidGate(IAsynchronousMessage):
    def __init__(self):
        self.last_seen: dict = {}
        self.last_barrier_trigger: dict = {}
        self.serial_connection = None
        self._setup_serial()
        print(f"[gate] Mode: {GATE_MODE.upper()} | Plaza: {PLAZA_ID} | Lane: {LANE_ID or 'unset'}")

    # ── Serial / Barrier ────────────────────────────────────────────────────

    def _setup_serial(self):
        try:
            self.serial_connection = serial.Serial(
                port=SERIAL_PORT, baudrate=SERIAL_BAUD, timeout=1
            )
            print(f"[serial] Connected on {SERIAL_PORT} at {SERIAL_BAUD} baud")
        except Exception as exc:
            print(f"[serial] Failed: {exc}")
            self.serial_connection = None

    def _send_serial(self, cmd: str) -> bool:
        try:
            if not self.serial_connection or not self.serial_connection.is_open:
                self._setup_serial()
            if self.serial_connection and self.serial_connection.is_open:
                self.serial_connection.write(cmd.encode())
                return True
        except Exception as exc:
            print(f"[serial] Error: {exc}")
            self.serial_connection = None
        return False

    def _open_barrier(self):
        self._send_serial('o')

    def _close_barrier(self):
        try:
            requests.get(THANKYOU_URL, timeout=2)
        except Exception:
            pass
        self._send_serial('f')

    def _schedule_close(self):
        def _close():
            time.sleep(OPEN_SECONDS)
            self._close_barrier()
        threading.Thread(target=_close, daemon=True).start()

    # ── Display ─────────────────────────────────────────────────────────────

    def _show_fare(self, fare):
        try:
            requests.get(FARE_DISPLAY.format(fare=fare), timeout=2)
        except Exception:
            pass

    def _show_denied(self):
        try:
            requests.get(f"http://{DISPLAY_IP}/?vehicle_number=Q.TAG&fare_amount=0", timeout=2)
        except Exception:
            pass

    # ── RFID Callback ────────────────────────────────────────────────────────

    def OutputTags(self, tag):
        try:
            tag_epc = getattr(tag, '_EPC', '')
            tag_tid = normalize_tid(getattr(tag, '_TID', ''))
            now = datetime.now()

            # deduplicate within 1 second
            key = (tag_epc, tag_tid)
            if key in self.last_seen and (now - self.last_seen[key]).total_seconds() <= 1:
                return
            self.last_seen[key] = now

            print(f"\n>>> EPC: {tag_epc} | TID: {tag_tid} | {now} | mode={GATE_MODE.upper()}")

            # per-tag cooldown
            now_ts = time.time()
            if tag_tid in self.last_barrier_trigger:
                elapsed = now_ts - self.last_barrier_trigger[tag_tid]
                if elapsed < TAG_COOLDOWN:
                    print(f"[cooldown] {tag_tid} — wait {TAG_COOLDOWN - elapsed:.1f}s")
                    return
            self.last_barrier_trigger[tag_tid] = now_ts

            result = ApiClient.process_tag(tag_tid)

            if not result.get('success'):
                reason = result.get('reason', 'denied')
                print(f"[gate] DENIED — {reason}")
                self._show_denied()
                return

            # On success Django returns charge (exit) or current_balance (entry)
            fare = result.get('charge') or result.get('current_balance', '0')
            self._show_fare(fare)
            self._open_barrier()
            self._schedule_close()

            if GATE_MODE == 'exit':
                print(
                    f"[gate] EXIT OK — vehicle: {result.get('vehicle')} "
                    f"charge: Rs.{result.get('charge')} "
                    f"balance: Rs.{result.get('balance_remaining')}"
                )
            else:
                print(
                    f"[gate] ENTRY OK — vehicle: {result.get('vehicle')} "
                    f"balance: Rs.{result.get('current_balance')}"
                )

        except Exception as exc:
            print(f"[error] OutputTags: {exc}")

    def OutputTagsOver(self, connID):
        print(f"[reader] Connection {connID} finished")

    def cleanup(self):
        if self.serial_connection and self.serial_connection.is_open:
            self.serial_connection.close()

    # ── Entry Point ──────────────────────────────────────────────────────────

    @staticmethod
    def main():
        if not PLAZA_ID or PLAZA_ID == '00000000-0000-0000-0000-000000000000':
            print("[ERROR] plaza_id not set in rfid_config.ini — cannot start.")
            return
        if not OPERATOR_TOKEN:
            print("[ERROR] operator_token not set in rfid_config.ini — cannot start.")
            return

        gate = RfidGate()
        reader = Reader()
        try:
            try:
                requests.get(WELCOME_URL, timeout=2)
            except Exception:
                pass

            tcp = f"TCP:{READER_HOST}:{READER_PORT}"
            if reader.initReader(tcp, gate):
                print(f"[reader] Connected to {tcp}")
                reader.paramSet(
                    EReaderEnum.WO_RFIDReadExtended,
                    [ReadExtendedArea_Model(EReadBank.TID, 0, 6, "")]
                )
                while True:
                    try:
                        requests.get(WELCOME_URL, timeout=2)
                    except Exception:
                        pass
                    print("[reader] Scanning...")
                    reader.inventory()
                    time.sleep(1)
            else:
                print("[reader] Failed to connect")
        except KeyboardInterrupt:
            print("\n[gate] Interrupted")
        finally:
            gate.cleanup()


if __name__ == '__main__':
    RfidGate.main()
```

- [ ] **Step 2: Verify the script parses without syntax errors**

```bash
cd "/home/makhshaf-haider/Downloads/m tag"
python3 -c "import ast, sys; ast.parse(open('rfid_final.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 3: Verify config file is read correctly**

```bash
cd "/home/makhshaf-haider/Downloads/m tag"
python3 -c "
import configparser
cfg = configparser.ConfigParser()
cfg.read('rfid_config.ini')
print('mode   =', cfg.get('gate','mode'))
print('plaza  =', cfg.get('gate','plaza_id'))
print('api    =', cfg.get('api','base_url'))
"
```

Expected:
```
mode   = entry
plaza  = 00000000-0000-0000-0000-000000000000
api    = http://192.168.78.8:8000
```

---

## Task 5: Populate rfid_config.ini with Real Values

The config ships with placeholder UUIDs. Before running on the actual hardware, the operator must fill in the real values.

- [ ] **Step 1: Get operator JWT token**

  On the machine that has access to the Django backend:

```bash
curl -s -X POST http://192.168.78.8:8000/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"phone": "<operator_phone>", "password": "<operator_password>"}' \
  | python3 -m json.tool
```

  Copy the `access` value.

- [ ] **Step 2: Get the plaza UUID**

```bash
curl -s http://192.168.78.8:8000/api/v1/tolls/plazas/ \
  -H "Authorization: Bearer <access_token>" \
  | python3 -m json.tool
```

  Find the plaza for this gate and copy its `id`.

- [ ] **Step 3: Edit `rfid_config.ini`**

  Replace `PASTE_OPERATOR_JWT_HERE` with the `access` token.  
  Replace `plaza_id` UUID with the value from Step 2.  
  Set `mode = entry` for entry gates, `mode = exit` for exit gates.  
  Set `lane_id` if the lane UUID is known (optional).

- [ ] **Step 4: Test end-to-end with a dry run (barrier disconnected)**

```bash
cd "/home/makhshaf-haider/Downloads/m tag"
python3 -c "
import rfid_final as g
import rfid_final
result = rfid_final.ApiClient.process_tag('TEST_SERIAL_NOT_IN_DB')
print('Result:', result)
"
```

  Expected: `Result: {'success': False, 'reason': 'Tag not found'}` (API is reachable, tag unknown).

---

## Checklist: Spec Coverage

| Requirement | Covered in |
|---|---|
| RFID calls Django entry endpoint | Task 4 — `ApiClient.process_tag` + `ENTRY_URL` |
| RFID calls Django exit endpoint | Task 4 — `EXIT_URL` when `mode=exit` |
| Entry/exit mode configurable per gate | Task 3 — `rfid_config.ini [gate] mode` |
| Barrier still opens/closes via serial | Task 4 — `_open_barrier`/`_close_barrier` |
| Display still shows fare/thankyou | Task 4 — `_show_fare`/`_close_barrier` |
| Tag cooldown preserved | Task 4 — `last_barrier_trigger` dict |
| JazzCash HMAC-SHA256 signature | Task 1 — `_secure_hash` helper |
| Tag reissue endpoint | Task 2 — `POST /api/v1/vehicles/tags/<id>/reissue/` |
| Old tag deactivated on reissue | Task 2 — `Tag.objects.filter(...).update(status=EXPIRED)` |
