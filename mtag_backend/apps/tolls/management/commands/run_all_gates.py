"""
Start all booth gate controllers from a single master config file.

Usage:
    python manage.py run_all_gates
    python manage.py run_all_gates --config /path/to/gates.ini

gates.ini format — one [booth_*] section per booth, shared [defaults] section:

    [defaults]
    serial_baud = 115200
    reader_port = 9090
    open_seconds = 2.0
    tag_cooldown = 5.0
    display_ip = 192.168.78.12

    [booth_kpt_1]
    mode = entry
    plaza_id = <uuid>
    lane_id =
    reader_host = 192.168.78.8
    serial_port = /dev/ttyUSB0
    display_ip = 192.168.1.101     # overrides [defaults]

Each booth runs in its own thread. Ctrl+C stops all.
"""
import configparser
import os
import threading

from django.core.management.base import BaseCommand, CommandError

from .run_gate import GateController, resolve_plaza_lane


class PrefixWriter:
    """Wraps stdout to prefix every line with the booth name."""
    def __init__(self, inner, prefix: str):
        self._inner = inner
        self._prefix = prefix

    def write(self, msg: str):
        self._inner.write(f"[{self._prefix}] {msg}")

    def flush(self):
        pass


class Command(BaseCommand):
    help = "Start all booth gate controllers from gates.ini"

    def add_arguments(self, parser):
        parser.add_argument(
            '--config',
            default='gates.ini',
            help='Path to gates.ini (default: gates.ini in CWD)',
        )

    def handle(self, *args, **options):
        cfg_path = options['config']
        if not os.path.exists(cfg_path):
            raise CommandError(
                f"Config file not found: {cfg_path}\n"
                "Create gates.ini next to manage.py. See the sample file for format."
            )

        cfg = configparser.ConfigParser()
        cfg.read(cfg_path)

        # Pull defaults
        defaults = cfg['defaults'] if cfg.has_section('defaults') else {}

        def get(section, key, fallback=None):
            return cfg.get(section, key, fallback=defaults.get(key, fallback))

        booth_sections = [s for s in cfg.sections() if s.startswith('booth_')]
        if not booth_sections:
            raise CommandError("No [booth_*] sections found in gates.ini.")

        self.stdout.write(self.style.SUCCESS(
            f"Starting {len(booth_sections)} booth(s): {', '.join(booth_sections)}"
        ))

        threads = []
        stop_event = threading.Event()

        for section in booth_sections:
            plaza_code  = get(section, 'plaza_code', '').strip().upper()
            plaza_id    = get(section, 'plaza_id', '').strip()
            lane_number = get(section, 'lane_number', '').strip() or None
            lane_id     = get(section, 'lane_id', '').strip() or None

            gate_mode = get(section, 'mode', 'entry').strip().lower()
            if gate_mode not in ('entry', 'exit'):
                self.stdout.write(self.style.WARNING(
                    f"  [{section}] invalid mode '{gate_mode}' — skipping"
                ))
                continue

            try:
                plaza_id, lane_id = resolve_plaza_lane(plaza_code, plaza_id, lane_number, lane_id)
            except CommandError as exc:
                self.stdout.write(self.style.WARNING(f"  [{section}] {exc} — skipping"))
                continue

            gate = GateController(
                gate_mode=gate_mode,
                plaza_id=plaza_id,
                lane_id=lane_id,
                serial_port=get(section, 'serial_port', '/dev/ttyUSB0'),
                serial_baud=int(get(section, 'serial_baud', '115200')),
                open_secs=float(get(section, 'open_seconds', '2.0')),
                display_ip=get(section, 'display_ip', '192.168.78.12'),
                tag_cooldown=float(get(section, 'tag_cooldown', '5.0')),
                stdout=PrefixWriter(self.stdout, section),
            )

            reader_host = get(section, 'reader_host', '192.168.78.8')
            reader_port = int(get(section, 'reader_port', '9090'))

            t = threading.Thread(
                target=self._run_booth,
                args=(gate, reader_host, reader_port, section, stop_event),
                name=section,
                daemon=True,
            )
            threads.append(t)

        if not threads:
            raise CommandError("No valid booths to start.")

        for t in threads:
            t.start()

        self.stdout.write(self.style.SUCCESS(
            f"All booths running. Press Ctrl+C to stop."
        ))

        try:
            for t in threads:
                t.join()
        except KeyboardInterrupt:
            self.stdout.write("\nStopping all booths...")
            stop_event.set()

    def _run_booth(self, gate: GateController, reader_host: str, reader_port: int,
                   name: str, stop_event: threading.Event):
        try:
            gate.run(reader_host, reader_port)
        except CommandError as exc:
            self.stdout.write(f"[{name}] ERROR: {exc}")
        except Exception as exc:
            self.stdout.write(f"[{name}] Crashed: {exc}")
