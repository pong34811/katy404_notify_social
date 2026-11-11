"""Single-machine queue runner. Caller must enforce the global publish gate."""

import os

from django.core.management.base import CommandError
from django.db.models import Case, F, IntegerField, Q, Value, When
from django.utils import timezone
from filelock import Timeout

from . import downloader
from .facebook import Facebook
from .locking import worker_lock
from .models import PublishJob, Video
from .notifications import valid_thumbnail_url
from .services import (
    DOWNLOAD_RETRY,
    MAX_VIDEO_SCHEDULE_AHEAD,
    MIN_VIDEO_SCHEDULE_AHEAD,
    delete_verified_video_original,
    duplicate_notification_video_ids,
    dispatch_job,
    fetch_original,
    prepare_video,
    purge_stale_source_metadata,
    verify_job,
)
from .youtube import YouTube


def process_queue(limit, include_unscheduled=False, job_ids=None):
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
            if job_ids is None:
                purge_stale_source_metadata(now)
            interrupted = PublishJob.objects.filter(state="sending", remote_id="")
            uncertain = PublishJob.objects.filter(state="sending").exclude(remote_id="")
            if job_ids is not None:
                interrupted = interrupted.filter(pk__in=job_ids)
                uncertain = uncertain.filter(pk__in=job_ids)
            interrupted.update(
                state="needs_review", error_code="worker_interrupted_during_post", updated_at=now
            )
            uncertain.update(state="verifying", retry_at=now, updated_at=now)
            schedule_start = now + MIN_VIDEO_SCHEDULE_AHEAD
            schedule_end = now + MAX_VIDEO_SCHEDULE_AHEAD
            videos = (
                Video.objects.filter(
                    publishjob__kind=PublishJob.Kind.VIDEO,
                    publishjob__state=PublishJob.State.PENDING,
                    publishjob__scheduled_at__lte=schedule_end,
                    baseline=False,
                    available=True,
                    channel__enabled=True,
                    channel__ownership_confirmed=True,
                )
                .exclude(state__in=[Video.State.PUBLISHED, Video.State.SCHEDULED])
                .distinct()
                .select_related("channel__page")
                .order_by(
                    "publishjob__scheduled_at",
                    F("prepared_at").asc(nulls_first=True),
                    "first_seen_at",
                )
            )
            if job_ids is not None:
                videos = videos.filter(publishjob__in=job_ids)
            # Snapshot a bounded set of IDs before updating the ordering column.
            for video in list(videos[:limit]):
                if fetch_original(video, downloader, now):
                    video.refresh_from_db()
                prepare_video(video)
            if job_ids is None:
                auto_candidates = (
                    Video.objects.filter(
                        baseline=False,
                        available=True,
                        state__in=[
                            Video.State.WAITING_FILE,
                            Video.State.WAITING_RIGHTS,
                            Video.State.WAITING_THUMBNAIL,
                            Video.State.READY,
                            Video.State.READY_PHOTO,
                        ],
                        channel__enabled=True,
                        channel__ownership_confirmed=True,
                        channel__page__auto_publish=True,
                        publishjob__isnull=True,
                    )
                    .select_related("channel__page")
                    .order_by("first_seen_at", "video_id")
                )
                duplicates_by_page = {}
                prepared = 0
                for video in auto_candidates.iterator():
                    if prepared >= limit:
                        break
                    page = video.channel.page
                    if not (page.post_video or page.post_photo):
                        continue
                    if page.pk not in duplicates_by_page:
                        duplicates_by_page[page.pk] = duplicate_notification_video_ids(page)
                    if video.pk in duplicates_by_page[page.pk]:
                        continue
                    if video.state == Video.State.WAITING_RIGHTS and not video.rights_confirmed:
                        continue
                    if (
                        video.state == Video.State.WAITING_THUMBNAIL
                        and not valid_thumbnail_url(video.thumbnail_url)
                    ):
                        continue
                    has_source_media = bool(video.original) or video.landscape_confirmed
                    if not has_source_media:
                        if os.getenv("YT_DOWNLOAD") != "1":
                            continue
                        if video.download_attempted_at and video.download_attempted_at > now - DOWNLOAD_RETRY:
                            continue
                        fetch_original(video, downloader, now)
                        video.refresh_from_db()
                    prepare_video(video)
                    prepared += 1
            processed = 0
            cleanup_jobs = (
                PublishJob.objects.filter(
                    state__in=[PublishJob.State.SUCCEEDED, PublishJob.State.SCHEDULED],
                    kind="video",
                    error_code="original_cleanup_failed",
                )
                .select_related("video")
                .order_by("created_at", "pk")
            )
            if job_ids is not None:
                cleanup_jobs = cleanup_jobs.filter(pk__in=job_ids)
            for job in cleanup_jobs[:limit]:
                delete_verified_video_original(job)
                processed += 1
            jobs = (
                PublishJob.objects.filter(
                    Q(state="verifying")
                    | Q(state="scheduled", scheduled_at__lte=now)
                    | Q(state="pending", scheduled_at__lte=now)
                    | Q(
                        state="pending",
                        scheduled_at__gte=schedule_start,
                        scheduled_at__lte=schedule_end,
                    )
                )
                .select_related("page", "video__channel__page")
                .order_by(
                    "scheduled_at",
                    F("attempted_at").asc(nulls_first=True),
                    "created_at",
                    "pk",
                )
            )
            if include_unscheduled:
                jobs = jobs | PublishJob.objects.filter(state="pending", scheduled_at__isnull=True)
            if job_ids is not None:
                jobs = jobs.filter(pk__in=job_ids)
            verifying_jobs = jobs.filter(state=PublishJob.State.VERIFYING)
            if verifying_jobs.exists():
                # Never start another POST while an earlier one awaits exact-object readback.
                jobs = verifying_jobs
            jobs = jobs.select_related("page", "video__channel__page").order_by(
                Case(
                    When(state=PublishJob.State.VERIFYING, then=Value(0)),
                    default=Value(1),
                    output_field=IntegerField(),
                ),
                "scheduled_at",
                F("attempted_at").asc(nulls_first=True),
                "created_at",
                "pk",
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
