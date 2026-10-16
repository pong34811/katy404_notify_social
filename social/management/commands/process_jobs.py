"""Preview by default. Three explicit gates protect external publishing."""

import os

from django.core.management.base import BaseCommand, CommandError

from social.models import PublishJob, Video


class Command(BaseCommand):
    help = "Preview counts, or process jobs with --publish and LIVE_PUBLISH=1."

    def add_arguments(self, parser):
        parser.add_argument("--publish", action="store_true")
        parser.add_argument("--limit", type=int, default=10)

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 100:
            raise CommandError("limit_must_be_1_to_100")
        if not options["publish"]:
            self.stdout.write(
                f"preview videos={Video.objects.filter(baseline=False).count()} jobs={PublishJob.objects.count()}"
            )
            return
        if os.getenv("LIVE_PUBLISH", "0") != "1":
            raise CommandError("live_publish_disabled")
        from social.worker import process_queue

        result = process_queue(options["limit"])
        self.stdout.write(result)
