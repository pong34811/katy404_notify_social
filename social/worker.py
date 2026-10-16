"""Single-machine queue runner. Caller must enforce the global publish gate."""

import os

from django.core.management.base import CommandError
from django.db.models import F
from django.utils import timezone
from filelock import Timeout

from . import downloader
from .facebook import Facebook
from .locking import worker_lock
from .models import PublishJob, Video
from .services import (
    delete_verified_video_original,
    dispatch_job,
    fetch_original,
    prepare_video,
    purge_stale_source_metadata,
    verify_job,
)
from .youtube import YouTube


def process_queue(limit):
    try:
        with worker_lock():
            try:
                yt = YouTube(os.getenv("YOUTUBE_API_KEY", ""))
                version = os.getenv("FB_GRAPH_VERSION", "v26.0")
                if version != "v26.0":
                    raise ValueError("unsupported_version")
            except ValueError:
                raise CommandError("integration_configuration_invalid") from None
            now = timezone.now()
            purge_stale_source_metadata(now)
            PublishJob.objects.filter(state="sending", remote_id="").update(
                state="needs_review", error_code="worker_interrupted_during_post", updated_at=now
            )
            PublishJob.objects.filter(state="sending").exclude(remote_id="").update(
                state="verifying", retry_at=now, updated_at=now
            )
            videos = (
                Video.objects.filter(
                    baseline=False,
                    available=True,
                    channel__enabled=True,
                    channel__ownership_confirmed=True,
                )
                .select_related("channel__page")
                .order_by(F("prepared_at").asc(nulls_first=True), "first_seen_at")
            )
            # Snapshot a bounded set of IDs before updating the ordering column.
            for video in list(videos[:100]):
                if fetch_original(video, downloader, now):
                    video.refresh_from_db()
                prepare_video(video)
            processed = 0
            cleanup_jobs = (
                PublishJob.objects.filter(
                    state="succeeded",
                    kind="video",
                    error_code="original_cleanup_failed",
                )
                .select_related("video")
                .order_by("created_at", "pk")
            )
            for job in cleanup_jobs[:limit]:
                delete_verified_video_original(job)
                processed += 1
            jobs = (
                PublishJob.objects.filter(state__in=["pending", "verifying"])
                .select_related("page", "video__channel__page")
                .order_by(F("attempted_at").asc(nulls_first=True), "created_at", "pk")
            )
            for job in jobs.iterator(chunk_size=100):
                if processed >= limit:
                    break
                if job.state == "pending" and not job.page.auto_publish:
                    continue
                if job.state == "verifying" and job.retry_at and job.retry_at > now:
                    continue
                try:
                    fb = Facebook(job.page.page_id, os.getenv(job.page.token_env, ""), version)
                except ValueError:
                    PublishJob.objects.filter(pk=job.pk).update(
                        error_code="page_configuration_invalid", updated_at=now
                    )
                    continue
                PublishJob.objects.filter(pk=job.pk).update(attempted_at=now)
                if job.state == "verifying":
                    verify_job(job, fb, now)
                else:
                    dispatch_job(job, yt, fb, now)
                processed += 1
                if processed >= limit:
                    break
            return f"processed={processed}"
    except Timeout:
        return "worker_busy"
