"""
ANPR gate controller — connects to the quick-toll-system WebSocket server
(port 3003) and processes toll transactions based on detected plate numbers.

The quick-toll-system broadcasts:
    { "type": "plateNumber", "data": { "plateNumber": "ABC-1234", ... } }

This command receives those events, looks up the vehicle + tag, and runs the
same EntryService / ExitService logic used by the RFID gate.

Usage:
    python manage.py run_anpr_gate
    python manage.py run_anpr_gate --config /path/to/anpr_config.ini

Sample anpr_config.ini:
    [gate]
    mode = entry               # entry or exit
    plaza_code = KPT
    lane_number = 1
    plate_cooldown = 5.0       # seconds to ignore same plate again

    [anpr]
    ws_url = ws://localhost:3003

    [barrier]
    port = /dev/ttyUSB0
    baudrate = 115200
    open_seconds = 2.0

    [display]
    display_ip = 192.168.78.12

    [offline]
    db_path =                  # leave blank for default (manage.py dir)
"""
import configparser
import json
import os
import re
import threading
import time
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db.models import CharField, F, Func

from apps.tolls.management.commands.run_gate import (
    GateController,
    resolve_plaza_lane,
)


class _NormPlate(Func):
    """PostgreSQL: strip all non-alphanumeric chars and uppercase."""
    function = 'REGEXP_REPLACE'
    template = "UPPER(%(function)s(%(expressions)s, '[^A-Za-z0-9]', '', 'g'))"
    output_field = CharField()


def _normalize(plate: str) -> str:
    return re.sub(r'[^A-Z0-9]', '', plate.upper())


class AnprGateController(GateController):
    """
    Extends GateController with a plate-number based lookup.
    All barrier / serial / display / portal-poll / offline logic is inherited.
    """

    def on_plate(self, plate_number: str):
        """Called when the ANPR WebSocket emits a plateNumber event."""
        from apps.vehicles.models import Vehicle, TagStatus

        now = datetime.now()
        key = plate_number.upper()
        norm_key = _normalize(key)

        with self._lock:
            # Per-plate cooldown keyed on normalized plate so KDE-1836 and KDE1836 share cooldown
            now_m = time.monotonic()
            last_t = self.last_trigger.get(norm_key)
            if last_t and (now_m - last_t) < self.tag_cooldown:
                remaining = self.tag_cooldown - (now_m - last_t)
                self.stdout.write(f"[cooldown] {key} — wait {remaining:.1f}s")
                return
            self.last_trigger[norm_key] = now_m

        self.stdout.write(
            f"\n>>> PLATE: {key} | {now} | mode={self.gate_mode.upper()}"
        )

        # Resolve plate → vehicle → tag
        # Normalize both sides: strip dashes/spaces, uppercase, then compare.
        # KDE-1836 == KDE1836 == KDE 1836
        vehicle = (
            Vehicle.objects
            .annotate(norm=_NormPlate(F('plate_number')))
            .filter(norm=norm_key)
            .select_related('tag')
            .first()
        )
        if vehicle is None:
            self.stdout.write(f"[anpr] DENIED — plate {key} not registered")
            self._show_denied()
            return

        tag = getattr(vehicle, 'tag', None)
        if tag is None:
            self.stdout.write(f"[anpr] DENIED — vehicle {key} has no tag")
            self._show_denied()
            return

        if tag.status != TagStatus.ACTIVE:
            self.stdout.write(f"[anpr] DENIED — tag {tag.tag_serial} is {tag.status}")
            self._show_denied()
            return

        # Delegate to the same _process_tag used by RFID gate
        result = self._process_tag(tag.tag_serial)

        if not result.get('success'):
            reason = result.get('reason', 'denied')
            self.stdout.write(f"[anpr] DENIED — {reason}")
            if reason == 'Insufficient balance':
                bal = result.get('current_balance', '0')
                self._show_low_balance(bal)
            else:
                self._show_denied()
            return

        offline_flag = " [OFFLINE]" if result.get('offline') else ""
        fare = result.get('charge') or result.get('current_balance', '0')
        self._show_fare(fare)
        self._open_barrier()
        self._schedule_close()

        if self.gate_mode == 'exit':
            self.stdout.write(
                f"[anpr] EXIT OK{offline_flag} — vehicle: {key} "
                f"charge: Rs.{result.get('charge')} "
                f"balance: Rs.{result.get('balance_remaining')}"
            )
        else:
            self.stdout.write(
                f"[anpr] ENTRY OK{offline_flag} — vehicle: {key} "
                f"balance: Rs.{result.get('current_balance')}"
            )

    def run_ws(self, ws_url: str):
        """Connect to the quick-toll-system WebSocket and listen for plates."""
        import websocket  # websocket-client

        self._show_welcome()
        self.stdout.write(f"[anpr] Connecting to {ws_url} ...")

        def on_message(ws_app, raw):
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                return
            if msg.get('type') == 'plateNumber':
                plate = (msg.get('data') or {}).get('plateNumber', '').strip()
                if plate:
                    self.on_plate(plate)

        def on_open(ws_app):
            self.stdout.write(f"[anpr] Connected to {ws_url}")

        def on_close(ws_app, code, reason):
            self.stdout.write(f"[anpr] Disconnected (code={code}) — reconnecting in 5s")

        def on_error(ws_app, error):
            self.stdout.write(f"[anpr] WS error: {error}")

        while self._running:
            try:
                app = websocket.WebSocketApp(
                    ws_url,
                    on_open=on_open,
                    on_message=on_message,
                    on_close=on_close,
                    on_error=on_error,
                )
                # run_forever blocks; reconnect_delay is handled by the outer loop
                app.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as exc:
                self.stdout.write(f"[anpr] Connection failed: {exc}")

            if self._running:
                time.sleep(5)  # wait before reconnecting

        self.stdout.write("[anpr] Stopped.")


class Command(BaseCommand):
    help = "Run the ANPR gate controller (reads plates from quick-toll WebSocket)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--config',
            default='anpr_config.ini',
            help='Path to anpr_config.ini (default: anpr_config.ini in CWD)',
        )

    def handle(self, *args, **options):
        cfg_path = options['config']
        if not os.path.exists(cfg_path):
            raise CommandError(
                f"Config file not found: {cfg_path}\n"
                "Create anpr_config.ini next to manage.py.\n\n"
                "[gate]\n"
                "mode = entry\n"
                "plaza_code = KPT\n"
                "lane_number = 1\n"
                "plate_cooldown = 5.0\n\n"
                "[anpr]\n"
                "ws_url = ws://localhost:3003\n\n"
                "[barrier]\n"
                "port = /dev/ttyUSB0\n"
                "baudrate = 115200\n"
                "open_seconds = 2.0\n\n"
                "[display]\n"
                "display_ip = 192.168.78.12\n"
            )

        cfg = configparser.ConfigParser()
        cfg.read(cfg_path)

        gate_mode    = cfg.get('gate', 'mode',          fallback='entry').strip().lower()
        plaza_id     = cfg.get('gate', 'plaza_id',      fallback='').strip()
        plaza_code   = cfg.get('gate', 'plaza_code',    fallback='').strip().upper()
        lane_id      = cfg.get('gate', 'lane_id',       fallback='').strip() or None
        lane_number  = cfg.get('gate', 'lane_number',   fallback='').strip() or None
        plate_cooldown = float(cfg.get('gate', 'plate_cooldown', fallback='5.0'))

        ws_url       = cfg.get('anpr', 'ws_url',        fallback='ws://localhost:3003')

        serial_port  = cfg.get('barrier', 'port',       fallback='/dev/ttyUSB0')
        serial_baud  = int(cfg.get('barrier', 'baudrate', fallback='115200'))
        open_secs    = float(cfg.get('barrier', 'open_seconds', fallback='2.0'))
        display_ip   = cfg.get('display', 'display_ip', fallback='192.168.78.12')

        if gate_mode not in ('entry', 'exit'):
            raise CommandError(f"Invalid gate mode '{gate_mode}' — must be 'entry' or 'exit'.")

        plaza_id, lane_id = resolve_plaza_lane(plaza_code, plaza_id, lane_number, lane_id)

        self.stdout.write(self.style.SUCCESS(
            f"[gate] Mode: {gate_mode.upper()} | Plaza: {plaza_id} | Lane: {lane_id or 'unset'}"
        ))

        gate = AnprGateController(
            gate_mode=gate_mode,
            plaza_id=plaza_id,
            lane_id=lane_id,
            serial_port=serial_port,
            serial_baud=serial_baud,
            open_secs=open_secs,
            display_ip=display_ip,
            tag_cooldown=plate_cooldown,
            stdout=self.stdout,
        )

        try:
            gate.run_ws(ws_url)
        except KeyboardInterrupt:
            self.stdout.write("\n[gate] Interrupted — shutting down")
        finally:
            gate._running = False
            if gate._serial and gate._serial.is_open:
                gate._serial.close()
