"""Make one operator-confirmed retry after a definite Facebook 413 rejection."""

import os

from django.core.management.base import BaseCommand, CommandError
from filelock import Timeout

from social.locking import worker_lock
from social.models import Page, PublishJob


class Command(BaseCommand):
    help = "Retry one video rejected with HTTP 413 after confirming no remote copy exists."

    def add_arguments(self, parser):
        parser.add_argument("job_id", type=int)
        parser.add_argument("--confirm-no-existing-post", action="store_true")

    def handle(self, *args, **options):
        if os.getenv("LIVE_PUBLISH", "0") != "1":
            raise CommandError("live_publish_disabled")
        if not options["confirm_no_existing_post"]:
            raise CommandError("confirm_no_existing_post_required")

        try:
            with worker_lock():
                job = PublishJob.objects.select_related("page", "video").get(pk=options["job_id"])
                if (
                    job.kind != PublishJob.Kind.VIDEO
                    or job.state != PublishJob.State.NEEDS_REVIEW
                    or job.error_code != "facebook_http_413"
                    or job.remote_id
                    or job.page.auto_publish
                    or not job.video.original
                    or not job.video.file_matches_video
                ):
                    raise CommandError("job_not_retryable_after_413")
                page = job.page
                page.auto_publish = True
                page.save(update_fields=["auto_publish"])
                job.state = PublishJob.State.PENDING
                job.error_code = ""
                job.retry_at = None
                job.save(update_fields=["state", "error_code", "retry_at", "updated_at"])
        except Timeout:
            raise CommandError("worker_busy") from None
        except PublishJob.DoesNotExist:
            raise CommandError("job_not_found") from None

        from social.worker import process_queue

        try:
            result = process_queue(1, include_unscheduled=True, job_ids=[job.pk])
            if result == "worker_busy":
                raise CommandError("worker_busy")
            job.refresh_from_db()
            if job.state == PublishJob.State.VERIFYING:
                # Read back the exact Facebook object once; later polls use the
                # normal verification schedule if encoding is not ready yet.
                process_queue(1, include_unscheduled=True, job_ids=[job.pk])
                job.refresh_from_db()
            self.stdout.write(
                f"job={job.pk} state={job.state} remote_id={job.remote_id or '-'} "
                f"error={job.error_code or '-'}"
            )
        finally:
            try:
                with worker_lock():
                    Page.objects.filter(pk=page.pk).update(auto_publish=False)
            except Timeout:
                Page.objects.filter(pk=page.pk).update(auto_publish=False)
