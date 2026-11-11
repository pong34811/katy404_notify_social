"""Publish one specific pending Page job with the regular worker safeguards."""

import os

from django.core.management.base import BaseCommand, CommandError
from filelock import Timeout

from social.locking import worker_lock
from social.models import Page, PublishJob
from social.services import _notification_title_key


class Command(BaseCommand):
    help = "Publish one pending video after confirming no existing Page post is present."

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
                    or job.state != PublishJob.State.PENDING
                    or job.scheduled_at is not None
                    or job.remote_id
                    or job.page.auto_publish
                    or not job.page.post_video
                    or not job.video.original
                    or not job.video.file_matches_video
                ):
                    raise CommandError("job_not_publishable")

                key = _notification_title_key(job.video.title)
                already_sent = PublishJob.objects.filter(
                    page=job.page,
                    state__in=[
                        PublishJob.State.SUCCEEDED,
                        PublishJob.State.SCHEDULED,
                        PublishJob.State.VERIFYING,
                        PublishJob.State.SENDING,
                    ],
                ).exclude(pk=job.pk).select_related("video")
                if key and any(
                    _notification_title_key(other.video.title) == key for other in already_sent
                ):
                    raise CommandError("duplicate_notification_skipped")

                page = job.page
                page.auto_publish = True
                page.save(update_fields=["auto_publish"])
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
