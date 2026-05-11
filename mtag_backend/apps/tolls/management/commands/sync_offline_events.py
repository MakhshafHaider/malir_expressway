"""
Django management command: sync_offline_events

Periodically syncs local SQLite offline exit events back to central PostgreSQL.

Usage:
    python manage.py sync_offline_events --config booth_configs/booth_10_shf.ini
    python manage.py sync_offline_events --config booth_configs/booth_10_shf.ini --once

Config file sections used:
    [gate]
    plaza_code  = SHF
    lane_number = 10

    [offline]
    db_path = /path/to/offline_cache.db   # optional; default: offline_cache.db next to manage.py

Default loop interval: 30 seconds.
"""

import configparser
import logging
import os
import time

from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)

DEFAULT_LOOP_INTERVAL = 30  # seconds


class Command(BaseCommand):
    help = (
        "Sync offline exit events from local SQLite to central PostgreSQL. "
        "Also pulls fresh tag/rate/trip data from central DB into the local cache."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--config',
            required=True,
            help=(
                'Path to the booth config .ini file '
                '(same format as run_gate uses — must contain [gate] and [offline] sections).'
            ),
        )
        parser.add_argument(
            '--once',
            action='store_true',
            default=False,
            help='Run one sync cycle then exit (default: loop forever every 30 s).',
        )

    def handle(self, *args, **options):
        cfg_path: str = options['config']

        if not os.path.exists(cfg_path):
            raise CommandError(
                f"Config file not found: {cfg_path}\n\n"
                "Expected format:\n"
                "[gate]\n"
                "plaza_code  = SHF\n"
                "lane_number = 10\n\n"
                "[offline]\n"
                "db_path = /opt/booths/booth_10/offline_cache.db\n"
            )

        cfg = configparser.ConfigParser()
        cfg.read(cfg_path)

        # ── Read config values ────────────────────────────────────────────────
        plaza_code: str = cfg.get('gate', 'plaza_code', fallback='').strip().upper()
        lane_number_str: str = cfg.get('gate', 'lane_number', fallback='0').strip()
        try:
            lane_number: int = int(lane_number_str)
        except ValueError:
            raise CommandError(
                f"lane_number '{lane_number_str}' in [gate] section is not an integer."
            )

        # Resolve db_path: config > default next to manage.py
        manage_dir: str = os.path.dirname(
            os.path.abspath(
                os.path.join(
                    os.path.dirname(__file__), '..', '..', '..', '..', 'manage.py'
                )
            )
        )
        default_db_path: str = os.path.join(manage_dir, 'offline_cache.db')
        db_path: str = cfg.get('offline', 'db_path', fallback=default_db_path).strip()
        db_path = os.path.abspath(db_path)

        run_once: bool = options['once']

        self.stdout.write(
            self.style.SUCCESS(
                f"[sync] Starting offline event sync\n"
                f"  config       : {cfg_path}\n"
                f"  db_path      : {db_path}\n"
                f"  plaza_code   : {plaza_code or '(not set)'}\n"
                f"  lane_number  : {lane_number}\n"
                f"  mode         : {'once' if run_once else 'loop every 30s'}"
            )
        )

        if run_once:
            self._run_cycle(db_path)
        else:
            self._run_loop(db_path)

    # ── Internal methods ──────────────────────────────────────────────────────

    def _run_cycle(self, db_path: str) -> None:
        """Execute one full sync cycle: cache refresh + reconciliation."""
        from apps.tolls.offline_cache import CacheSync
        from apps.tolls.reconciliation_service import ReconciliationService

        # 1. Pull fresh data from central DB into local cache
        self.stdout.write("[sync] Running CacheSync.run_full_sync() …")
        try:
            syncer = CacheSync(db_path)
            cache_summary = syncer.run_full_sync()
            self.stdout.write(
                f"[sync] Cache sync done — "
                f"tags={cache_summary['tags']} "
                f"rates={cache_summary['rates']} "
                f"active_trips={cache_summary['active_trips']} "
                f"errors={len(cache_summary['errors'])}"
            )
            if cache_summary['errors']:
                for err in cache_summary['errors']:
                    self.stderr.write(f"[sync] Cache error: {err}")
        except Exception as exc:
            logger.exception("[sync] CacheSync.run_full_sync() raised an exception")
            self.stderr.write(
                self.style.WARNING(
                    f"[sync] Cache sync failed ({exc.__class__.__name__}: {exc}) — "
                    f"continuing with reconciliation anyway"
                )
            )

        # 2. Reconcile pending offline exit events
        self.stdout.write("[sync] Running ReconciliationService.sync_all_pending() …")
        try:
            recon = ReconciliationService(db_path)
            recon_summary = recon.sync_all_pending()
            self.stdout.write(
                self.style.SUCCESS(
                    f"[sync] Reconciliation done — "
                    f"total={recon_summary['total']} "
                    f"synced={recon_summary['synced']} "
                    f"failed={recon_summary['failed']} "
                    f"needs_manual_review={recon_summary['needs_manual_review']} "
                    f"skipped={recon_summary['skipped']}"
                )
            )
            if recon_summary['needs_manual_review'] > 0:
                self.stderr.write(
                    self.style.WARNING(
                        f"[sync] {recon_summary['needs_manual_review']} event(s) "
                        f"require manual review — check offline_exit_events table "
                        f"in {db_path}"
                    )
                )
        except Exception as exc:
            logger.exception(
                "[sync] ReconciliationService.sync_all_pending() raised an exception"
            )
            self.stderr.write(
                self.style.ERROR(
                    f"[sync] Reconciliation failed: {exc.__class__.__name__}: {exc}"
                )
            )

    def _run_loop(self, db_path: str) -> None:
        """Loop forever, running one cycle every DEFAULT_LOOP_INTERVAL seconds."""
        self.stdout.write(
            f"[sync] Entering loop — will sync every {DEFAULT_LOOP_INTERVAL}s. "
            f"Press Ctrl+C to stop."
        )
        while True:
            try:
                self._run_cycle(db_path)
            except Exception as exc:
                logger.exception("[sync] Unexpected error in loop cycle")
                self.stderr.write(
                    self.style.ERROR(
                        f"[sync] Cycle error: {exc.__class__.__name__}: {exc} "
                        f"— will retry in {DEFAULT_LOOP_INTERVAL}s"
                    )
                )

            try:
                time.sleep(DEFAULT_LOOP_INTERVAL)
            except KeyboardInterrupt:
                self.stdout.write("\n[sync] Interrupted — shutting down")
                break
