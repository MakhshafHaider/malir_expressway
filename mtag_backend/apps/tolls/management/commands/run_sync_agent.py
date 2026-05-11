"""
Standalone sync agent — pull+push in foreground (no Django server needed).

Usage:
    python manage.py run_sync_agent
    python manage.py run_sync_agent --interval 60
    python manage.py run_sync_agent --once
"""
import time
import logging
from django.core.management.base import BaseCommand
from apps.tolls.sync.pull_service import run_pull
from apps.tolls.sync.push_service import run_push

log = logging.getLogger('apps.tolls.sync.agent')


class Command(BaseCommand):
    help = "Run PostgreSQL sync agent (pull master→local, push local→master)"

    def add_arguments(self, parser):
        parser.add_argument('--interval', type=int, default=30,
                            help='Sync interval in seconds (default: 30)')
        parser.add_argument('--once', action='store_true',
                            help='Run one cycle and exit (for testing)')

    def handle(self, *args, **options):
        interval = options['interval']
        once     = options['once']

        self.stdout.write(f"[sync] Starting — interval={interval}s")

        while True:
            pull = run_pull()
            push = run_push()
            self.stdout.write(f"[sync] pull={pull}  push={push}")

            if once:
                break
            time.sleep(interval)
