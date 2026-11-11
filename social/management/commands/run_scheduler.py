"""Foreground backend loop that scans hourly and processes scheduled jobs each minute."""

import os
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Run scan_channels and process_jobs on fixed intervals until stopped (Ctrl+C)."

    def add_arguments(self, parser):
        parser.add_argument("--scan-interval", type=int, default=3600)
        parser.add_argument("--process-interval", type=int, default=60)
        parser.add_argument("--process-limit", type=int, default=10)
        parser.add_argument("--publish", action="store_true")
        parser.add_argument("--include-unscheduled", action="store_true")
        parser.add_argument("--once", action="store_true", help="Run each job once and exit.")

    def handle(self, *args, **options):
        scan_every, process_every = options["scan_interval"], options["process_interval"]
        if scan_every < 60 or process_every < 60:
            raise CommandError("interval_must_be_at_least_60_seconds")
        if not 1 <= options["process_limit"] <= 100:
            raise CommandError("process_limit_must_be_1_to_100")
        if options["include_unscheduled"] and not options["publish"]:
            raise CommandError("include_unscheduled_requires_publish")
        next_scan = next_process = 0.0
        while True:
            now = time.monotonic()
            if now >= next_scan:
                self._run("scan_channels", force=True)
                if options["publish"] and os.getenv("LIVE_PUBLISH", "0") == "1":
                    self._run("backfill_baseline_landscape", confirm_apply=True)
                next_scan = time.monotonic() + scan_every
            if now >= next_process:
                self._run(
                    "process_jobs",
                    publish=options["publish"],
                    include_unscheduled=options["include_unscheduled"],
                    limit=options["process_limit"],
                )
                next_process = time.monotonic() + process_every
            if options["once"]:
                return
            time.sleep(max(1.0, min(next_scan, next_process) - time.monotonic()))

    def _run(self, name, **kwargs):
        # Same commands and the same worker_lock as the wrappers; one failure must not stop the loop.
        try:
            call_command(name, stdout=self.stdout, stderr=self.stderr, **kwargs)
        except Exception as exc:
            self.stderr.write(f"{name}_failed {type(exc).__name__}")
