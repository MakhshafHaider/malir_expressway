"""
Django management command that replaces rfid_final.py.

Reads rfid_config.ini, connects to the RFID reader over TCP, and on every
tag scan calls EntryService / ExitService directly (no HTTP round-trip).
Barrier control is via a serial port; display updates are fire-and-forget
HTTP GETs.

Usage:
    python manage.py run_gate
    python manage.py run_gate --config /path/to/rfid_config.ini
"""
import configparser
import os
import threading
import time
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError


def resolve_plaza_lane(plaza_code: str, plaza_id: str, lane_number: str, lane_id: str):
    """Resolve human-readable plaza_code/lane_number to UUIDs from the DB."""
    from apps.tolls.models import Plaza, TollLane

    # Resolve plaza
    if plaza_code:
        try:
            plaza = Plaza.objects.get(code=plaza_code)
            plaza_id = str(plaza.id)
        except Plaza.DoesNotExist:
            raise CommandError(
                f"Plaza with code '{plaza_code}' not found in DB.\n"
                f"Available codes: {', '.join(Plaza.objects.values_list('code', flat=True))}"
            )
    elif not plaza_id or plaza_id == '00000000-0000-0000-0000-000000000000':
        codes = ', '.join(Plaza.objects.values_list('code', flat=True))
        raise CommandError(
            f"Set plaza_code (e.g. plaza_code = KPT) in config.\nAvailable: {codes}"
        )

    # Resolve lane
    if lane_number and not lane_id:
        try:
            lane = TollLane.objects.get(plaza_id=plaza_id, lane_number=int(lane_number))
            lane_id = str(lane.id)
        except TollLane.DoesNotExist:
            raise CommandError(
                f"Lane {lane_number} not found for plaza {plaza_code or plaza_id}."
            )

    return plaza_id, lane_id or None


class Command(BaseCommand):
    help = "Run the RFID gate controller (replaces rfid_final.py)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--config',
            default='rfid_config.ini',
            help='Path to rfid_config.ini (default: rfid_config.ini in CWD)',
        )

    def handle(self, *args, **options):
        cfg_path = options['config']
        if not os.path.exists(cfg_path):
            raise CommandError(
                f"Config file not found: {cfg_path}\n"
                "Create rfid_config.ini next to manage.py (see sample below).\n\n"
                "[gate]\n"
                "mode = entry          # entry or exit\n"
                "plaza_id = 00000000-0000-0000-0000-000000000000\n"
                "lane_id =             # optional uuid\n\n"
                "[scanner]\n"
                "reader_host = 192.168.78.8\n"
                "reader_port = 9090\n"
                "tag_cooldown = 5.0\n\n"
                "[barrier]\n"
                "port = /dev/ttyUSB0\n"
                "baudrate = 115200\n"
                "open_seconds = 2.0\n\n"
                "[display]\n"
                "display_ip = 192.168.78.12\n"
            )

        cfg = configparser.ConfigParser()
        cfg.read(cfg_path)

        gate_mode   = cfg.get('gate', 'mode',       fallback='entry').strip().lower()
        plaza_id    = cfg.get('gate', 'plaza_id',   fallback='').strip()
        plaza_code  = cfg.get('gate', 'plaza_code', fallback='').strip().upper()
        lane_id     = cfg.get('gate', 'lane_id',    fallback='').strip() or None
        lane_number = cfg.get('gate', 'lane_number', fallback='').strip() or None
        reader_host = cfg.get('scanner', 'reader_host', fallback='192.168.78.8')
        reader_port = int(cfg.get('scanner', 'reader_port', fallback='9090'))
        tag_cooldown = float(cfg.get('scanner', 'tag_cooldown', fallback='5.0'))
        serial_port = cfg.get('barrier', 'port',       fallback='/dev/ttyUSB0')
        serial_baud = int(cfg.get('barrier', 'baudrate', fallback='115200'))
        open_secs   = float(cfg.get('barrier', 'open_seconds', fallback='2.0'))
        display_ip  = cfg.get('display', 'display_ip', fallback='192.168.78.12')

        if gate_mode not in ('entry', 'exit'):
            raise CommandError(f"Invalid gate mode '{gate_mode}' — must be 'entry' or 'exit'.")

        plaza_id, lane_id = resolve_plaza_lane(plaza_code, plaza_id, lane_number, lane_id)

        self.stdout.write(self.style.SUCCESS(
            f"[gate] Mode: {gate_mode.upper()} | Plaza: {plaza_id} | Lane: {lane_id or 'unset'}"
        ))

        gate = GateController(
            gate_mode=gate_mode,
            plaza_id=plaza_id,
            lane_id=lane_id,
            serial_port=serial_port,
            serial_baud=serial_baud,
            open_secs=open_secs,
            display_ip=display_ip,
            tag_cooldown=tag_cooldown,
            stdout=self.stdout,
        )

        gate.run(reader_host, reader_port)


# ── Display helper ────────────────────────────────────────────────────────────

def _fire(url):
    """Fire-and-forget HTTP GET for display / indicator URLs."""
    import requests
    try:
        requests.get(url, timeout=2)
    except Exception:
        pass


def _bg_display(url):
    threading.Thread(target=_fire, args=(url,), daemon=True).start()


# ── Gate controller ───────────────────────────────────────────────────────────

class GateController:
    def __init__(
        self, *, gate_mode, plaza_id, lane_id,
        serial_port, serial_baud, open_secs,
        display_ip, tag_cooldown, stdout,
    ):
        self.gate_mode    = gate_mode
        self.plaza_id     = plaza_id
        self.lane_id      = lane_id
        self.open_secs    = open_secs
        self.display_ip   = display_ip
        self.tag_cooldown = tag_cooldown
        self.stdout       = stdout

        self.last_seen: dict    = {}   # (epc, tid) → datetime
        self.last_trigger: dict = {}   # tid → float (monotonic)
        self._lock = threading.Lock()
        self._running = True

        self._serial = None
        self._setup_serial(serial_port, serial_baud)

        # Start portal-triggered gate open polling thread
        threading.Thread(target=self._poll_portal_opens, daemon=True).start()

    # ── Serial ────────────────────────────────────────────────────────────────

    def _setup_serial(self, port, baud):
        try:
            import serial
            self._serial = serial.Serial(port=port, baudrate=baud, timeout=1)
            self.stdout.write(f"[serial] Connected on {port} at {baud} baud")
        except Exception as exc:
            self.stdout.write(f"[serial] Not available ({exc}) — barrier control disabled")
            self._serial = None

    def _send_serial(self, cmd: str):
        try:
            if self._serial and self._serial.is_open:
                self._serial.write(cmd.encode())
                return True
        except Exception as exc:
            self.stdout.write(f"[serial] Write error: {exc}")
            self._serial = None
        return False

    # ── Portal-triggered gate opens ───────────────────────────────────────────

    def _poll_portal_opens(self):
        """Poll DB every second for gate opens triggered via the admin portal."""
        from datetime import timedelta
        from django.utils import timezone
        from apps.tolls.models import PendingGateOpen

        while self._running:
            try:
                cutoff = timezone.now() - timedelta(seconds=30)
                cmd = PendingGateOpen.objects.filter(
                    plaza_id=self.plaza_id,
                    executed_at__isnull=True,
                    created_at__gte=cutoff,
                ).first()
                if cmd:
                    cmd.executed_at = timezone.now()
                    cmd.save(update_fields=['executed_at'])
                    self.stdout.write("[portal] Gate open triggered via portal")
                    self._open_barrier()
                    self._schedule_close()
            except Exception as exc:
                self.stdout.write(f"[poll] Error: {exc}")
            time.sleep(1)

    # ── Barrier ───────────────────────────────────────────────────────────────

    def _open_barrier(self):
        self.stdout.write("[barrier] OPENING")
        self._send_serial('o')

    def _close_barrier(self):
        self.stdout.write("[barrier] CLOSING")
        _bg_display(f"http://{self.display_ip}/thankyou")
        self._send_serial('f')

    def _schedule_close(self):
        def _do():
            time.sleep(self.open_secs)
            self._close_barrier()
        threading.Thread(target=_do, daemon=True).start()

    # ── Display ───────────────────────────────────────────────────────────────

    def _show_fare(self, fare):
        _bg_display(f"http://{self.display_ip}/?vehicle_number=Q.TAG&fare_amount={fare}")

    def _show_denied(self):
        _bg_display(f"http://{self.display_ip}/?vehicle_number=Q.TAG&fare_amount=0")

    def _show_low_balance(self, current_balance):
        _bg_display(f"http://{self.display_ip}/?vehicle_number=LOW.BAL&fare_amount={current_balance}")

    def _show_welcome(self):
        _bg_display(f"http://{self.display_ip}/?vehicle_number=WELCOME&take_slip")

    # ── Tag processing ────────────────────────────────────────────────────────

    def _process_tag(self, tag_serial: str) -> dict:
        from apps.tolls.services import EntryService, ExitService
        if self.gate_mode == 'entry':
            return EntryService.process_entry(tag_serial, self.plaza_id, self.lane_id)
        return ExitService.process_exit(tag_serial, self.plaza_id, self.lane_id)

    def on_tag(self, epc: str, tid: str):
        now = datetime.now()
        key = (epc, tid)

        with self._lock:
            # 1-second deduplication
            prev = self.last_seen.get(key)
            if prev and (now - prev).total_seconds() <= 1:
                return
            self.last_seen[key] = now

            # Per-tag cooldown
            now_m = time.monotonic()
            last_t = self.last_trigger.get(tid)
            if last_t and (now_m - last_t) < self.tag_cooldown:
                remaining = self.tag_cooldown - (now_m - last_t)
                self.stdout.write(f"[cooldown] {tid} — wait {remaining:.1f}s")
                return
            self.last_trigger[tid] = now_m

        self.stdout.write(f"\n>>> EPC: {epc} | TID: {tid} | {now} | mode={self.gate_mode.upper()}")

        result = self._process_tag(tid)

        if not result.get('success'):
            reason = result.get('reason', 'denied')
            self.stdout.write(f"[gate] DENIED — {reason}")
            self._show_denied()
            return

        offline_flag = " [OFFLINE]" if result.get('offline') else ""
        fare = result.get('charge') or result.get('current_balance', '0')
        self._show_fare(fare)
        self._open_barrier()
        self._schedule_close()

        if self.gate_mode == 'exit':
            self.stdout.write(
                f"[gate] EXIT OK{offline_flag} — vehicle: {result.get('vehicle')} "
                f"charge: Rs.{result.get('charge')} "
                f"balance: Rs.{result.get('balance_remaining')}"
            )
        else:
            self.stdout.write(
                f"[gate] ENTRY OK{offline_flag} — vehicle: {result.get('vehicle')} "
                f"balance: Rs.{result.get('current_balance')}"
            )

    # ── RFID reader loop ──────────────────────────────────────────────────────

    def run(self, reader_host: str, reader_port: int):
        try:
            from com.rfid.Reader import Reader
            from com.rfid.enumeration import EReaderEnum, EReadBank
            from com.rfid.models import ReadExtendedArea_Model
            from com.rfid.interface import IAsynchronousMessage
        except ImportError:
            raise CommandError(
                "com.rfid SDK not found. Install or add the SDK directory to PYTHONPATH.\n"
                "The SDK JAR/wheel should be placed alongside manage.py."
            )

        gate = self

        class _Listener(IAsynchronousMessage):
            def OutputTags(self, tag):
                try:
                    epc = getattr(tag, '_EPC', '') or ''
                    tid_raw = getattr(tag, '_TID', '') or ''
                    tid = tid_raw.replace(' ', '').upper()
                    gate.on_tag(epc, tid)
                except Exception as exc:
                    gate.stdout.write(f"[error] OutputTags: {exc}")

            def OutputTagsOver(self, conn_id):
                gate.stdout.write(f"[reader] Connection {conn_id} finished")

        listener = _Listener()
        reader = Reader()

        self._show_welcome()

        tcp = f"TCP:{reader_host}:{reader_port}"
        try:
            if not reader.initReader(tcp, listener):
                raise CommandError(f"[reader] Failed to connect to {tcp}")

            self.stdout.write(f"[reader] Connected to {tcp}")
            reader.paramSet(
                EReaderEnum.WO_RFIDReadExtended,
                [ReadExtendedArea_Model(EReadBank.TID, 0, 6, "")]
            )

            while True:
                self._show_welcome()
                self.stdout.write("[reader] Scanning...")
                reader.inventory()
                time.sleep(1)

        except KeyboardInterrupt:
            self.stdout.write("\n[gate] Interrupted — shutting down")
        finally:
            self._running = False
            if self._serial and self._serial.is_open:
                self._serial.close()
