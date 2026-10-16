"""Associate an operator-inspected remote object; never retries a publish."""

import os

from django.core.management.base import BaseCommand, CommandError
from filelock import Timeout

from social.facebook import Facebook
from social.locking import worker_lock
from social.models import PublishJob
from social.services import (
    delete_verified_video_original,
    mark_video_published_if_complete,
    safe_remote_url,
)


class Command(BaseCommand):
    help = "Reconcile after inspecting the exact Facebook object manually. Does not publish."

    def add_arguments(self, parser):
        parser.add_argument("job_id", type=int)
        parser.add_argument("--remote-id", required=True)

    def handle(self, *args, **options):
        try:
            with worker_lock():
                job = PublishJob.objects.select_related("page").get(pk=options["job_id"])
                if job.state not in {"needs_review", "verifying"}:
                    raise CommandError("job_not_reconcilable")
                remote_id = options["remote_id"]
                if job.remote_id and job.remote_id != remote_id:
                    raise CommandError("remote_id_is_immutable")
                try:
                    fb = Facebook(
                        job.page.page_id,
                        os.getenv(job.page.token_env, ""),
                        os.getenv("FB_GRAPH_VERSION", "v26.0"),
                    )
                    url = fb.verify(remote_id, job.kind)
                    if not url or not safe_remote_url(url):
                        raise ValueError("remote_not_ready")
                except Exception:
                    raise CommandError("remote_not_verified") from None
                job.remote_id, job.remote_url, job.state = remote_id, url, "succeeded"
                job.error_code, job.retry_at = "", None
                job.save(
                    update_fields=[
                        "remote_id",
                        "remote_url",
                        "state",
                        "error_code",
                        "retry_at",
                        "updated_at",
                    ]
                )
                mark_video_published_if_complete(job)
                delete_verified_video_original(job)
        except Timeout:
            raise CommandError("worker_busy") from None
        except PublishJob.DoesNotExist:
            raise CommandError("job_not_found") from None
        self.stdout.write("reconciled_without_publish")
