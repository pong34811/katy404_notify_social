import os

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from filelock import Timeout

from social.locking import worker_lock
from social.models import Channel
from social.services import purge_stale_source_metadata, scan_channel
from social.youtube import YouTube


class Command(BaseCommand):
    help = "Scan complete public uploads; first successful snapshot is a nonpublishing baseline."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **options):
        failures = 0
        try:
            with worker_lock():
                now = timezone.now()
                purge_stale_source_metadata(now)
                try:
                    api = YouTube(os.getenv("YOUTUBE_API_KEY", ""))
                except ValueError:
                    raise CommandError("youtube_configuration_invalid") from None
                for channel in Channel.objects.filter(enabled=True, ownership_confirmed=True):
                    if (
                        not options["force"]
                        and channel.last_scan_at
                        and timezone.localdate(channel.last_scan_at) == timezone.localdate(now)
                    ):
                        continue
                    try:
                        scan_channel(channel, api, now)
                    except Exception:
                        failures += 1
                        self.stderr.write(f"scan_failed channel={channel.pk}")
        except Timeout:
            self.stdout.write("worker_busy")
            return
        if failures:
            raise CommandError(f"scan_failed_count={failures}")
        self.stdout.write("scan_complete")
