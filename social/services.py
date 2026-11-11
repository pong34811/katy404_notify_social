"""Small workflow operations. Call write operations under worker_lock()."""

import os
import re
import shutil
import tempfile
import unicodedata
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from django.core.files import File
from django.db import transaction
from django.utils import timezone

from . import media
from .models import Channel, Page, PublishJob, Video
from .notifications import landscape_message, valid_thumbnail_url
from .validators import video_id_validator


def _meta_posting_block(error_code: str) -> bool:
    """True only for Meta's 368 posting block, which pauses the whole Page queue."""
    return bool(re.search(r"(?:_code_368|api_error_code_368)(?:_|$)", error_code))


def purge_stale_source_metadata(now):
    from django.contrib.admin.models import LogEntry
    from django.contrib.contenttypes.models import ContentType

    expired_ids = list(
        Video.objects.filter(source_checked_at__lte=now - timedelta(days=30)).values_list(
            "video_id", flat=True
        )
    )
    if not expired_ids:
        return 0
    count = Video.objects.filter(video_id__in=expired_ids).update(
        title="", thumbnail_url="", available=False
    )
    # Existing admin history stores object_repr as a denormalized title snapshot.
    content_type = ContentType.objects.get_for_model(Video)
    LogEntry.objects.filter(content_type=content_type, object_id__in=expired_ids).update(
        object_repr="Expired video metadata"
    )
    return count


def _notification_title_key(title):
    value = unicodedata.normalize("NFKC", title or "").casefold()
    value = re.sub(r"#\S+", " ", value)
    value = re.sub(r"^\s*re[- ]?upload\b", " ", value)
    value = re.sub(r"า{2,}", "า", value)
    value = re.sub(r"\s+", " ", value.replace("_", " ")).strip(" -_")
    return value


def duplicate_notification_video_ids(page):
    """Return unnotified videos that duplicate a prior Page title or another upload."""
    videos = list(
        Video.objects.filter(channel__page=page, available=True)
        .order_by("first_seen_at", "video_id")
        .values("video_id", "title")
    )
    if not videos:
        return set()

    job_video_ids = set(PublishJob.objects.filter(page=page).values_list("video_id", flat=True))
    notified_titles = {
        _notification_title_key(video["title"])
        for video in videos
        if video["video_id"] in job_video_ids and _notification_title_key(video["title"])
    }
    seen_titles = set()
    duplicates = set()
    for video in videos:
        video_id, key = video["video_id"], _notification_title_key(video["title"])
        if not key or video_id in job_video_ids:
            continue
        if key in notified_titles or key in seen_titles:
            duplicates.add(video_id)
        else:
            seen_titles.add(key)
    return duplicates


def scan_channel(channel, api, now):
    if not channel.enabled or not channel.ownership_confirmed:
        return
    snapshot = api.snapshot(channel.channel_id)
    for video_id, metadata in snapshot.items():
        video_id_validator(video_id)
        if not isinstance(metadata.get("title"), str):
            raise ValueError("invalid_source_metadata")
    with transaction.atomic():
        fresh = Channel.objects.get(pk=channel.pk)
        if not fresh.enabled or not fresh.ownership_confirmed:
            return
        baseline = fresh.baseline_at is None
        Video.objects.filter(channel=fresh).exclude(pk__in=snapshot).update(
            available=False, title="", thumbnail_url="", source_checked_at=now
        )
        for video_id, metadata in snapshot.items():
            video, created = Video.objects.get_or_create(
                video_id=video_id,
                defaults={
                    "channel": fresh,
                    "baseline": baseline,
                    "state": "baseline" if baseline else "waiting_file",
                },
            )
            if video.channel_id != fresh.pk:
                raise ValueError("duplicate_id_different_channel")
            video.title = metadata["title"]
            video.thumbnail_url = metadata.get("thumbnail_url", "")
            video.available = True
            video.source_checked_at = now
            if baseline:
                video.baseline, video.state = True, "baseline"
            video.save(
                update_fields=[
                    "title",
                    "thumbnail_url",
                    "available",
                    "source_checked_at",
                    "baseline",
                    "state",
                ]
            )
        if baseline:
            fresh.baseline_at = now
        fresh.last_scan_at = now
        fresh.save(update_fields=["baseline_at", "last_scan_at"])


DOWNLOAD_RETRY = timedelta(hours=1)


def fetch_original(video, dl, now):
    """Fetch a new vertical clip of an owned channel when YT_DOWNLOAD=1. True if a file was bound."""
    video = Video.objects.select_related("channel__page").get(pk=video.pk)
    if (
        os.getenv("YT_DOWNLOAD") != "1"
        or video.baseline
        or not video.available
        or video.original
        or video.landscape_confirmed
        or not video.channel.enabled
        or not video.channel.ownership_confirmed
        or not video.channel.page.auto_publish
        or (video.download_attempted_at and video.download_attempted_at > now - DOWNLOAD_RETRY)
    ):
        return False
    Video.objects.filter(pk=video.pk).update(download_attempted_at=now)
    workdir = Path(tempfile.mkdtemp(prefix="yt-dl-"))
    try:
        route = media.route_for_geometry(*dl.info(video.video_id))
        if route == "photo":
            Video.objects.filter(pk=video.pk).update(
                landscape_confirmed=True, rights_confirmed=True, media_error=""
            )
            return False
        if route != "video":
            Video.objects.filter(pk=video.pk).update(media_error="not_supported_geometry")
            return False
        path = dl.download(video.video_id, workdir)
        if not 0 < path.stat().st_size <= media.MAX_BYTES:
            raise ValueError("invalid_file_size")
        with path.open("rb") as handle:
            video.original.save(f"{video.video_id}.mp4", File(handle), save=False)
        Video.objects.filter(pk=video.pk).update(
            original=video.original.name,
            rights_confirmed=True,
            file_matches_video=True,
            media_error="",
            checked_name="",
        )
        return True
    except Exception:  # noqa: BLE001 - details may carry URLs; keep only a stable code
        Video.objects.filter(pk=video.pk).update(media_error="download_failed")
        return False
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def prepare_video(video):
    if (
        video.baseline
        or video.state in {Video.State.PUBLISHED, Video.State.SCHEDULED}
        or not video.available
        or not video.channel.enabled
        or not video.channel.ownership_confirmed
    ):
        return
    route = ""
    if not video.original and not video.landscape_confirmed:
        video.state = "waiting_file"
    elif not video.rights_confirmed:
        video.state = "waiting_rights"
    elif video.landscape_confirmed:
        route = "photo"
        video.media_error = ""
    elif not video.file_matches_video:
        video.state = "waiting_rights"
    else:
        if video.checked_name != video.original.name:
            try:
                inspected = media.route_for_geometry(*media.probe(video.original.path))
                video.inspected_kind = "" if inspected == "skip" else inspected
                video.media_error = "not_supported_geometry" if inspected == "skip" else ""
                video.checked_name = video.original.name
            except (ValueError, OSError):
                # A failed inspection is not a successful cache entry; the same original
                # must be retried on a later worker pass after ffprobe recovers.
                video.media_error = "invalid_or_unsupported_media"
                video.inspected_kind = ""
                video.checked_name = ""
        route = video.inspected_kind
        if video.media_error or not route or route == "skip":
            video.state, route = "rejected", ""
    page = video.channel.page
    if route:
        incompatible = (
            PublishJob.objects.filter(video=video, page=page, kind__in=["video", "photo"])
            .exclude(kind=route)
            .exists()
        )
        if incompatible:
            video.state, video.media_error, route = "needs_review", "delivery_route_changed", ""
        else:
            video.delivery_kind = route
            video.state = "ready_photo" if route == "photo" else "ready"
            if route == "photo" and not valid_thumbnail_url(video.thumbnail_url):
                video.state = "waiting_thumbnail"
    video.prepared_at = timezone.now()
    video.save(
        update_fields=[
            "state",
            "delivery_kind",
            "inspected_kind",
            "media_error",
            "checked_name",
            "prepared_at",
        ]
    )
    if video.state not in {"ready", "ready_photo"}:
        return
    PublishJob.objects.filter(
        video=video, page=page, state="blocked", remote_id="", error_code="media_recheck_failed"
    ).update(state="pending", error_code="")
    kinds = (
        [("photo", page.post_photo)]
        if route == "photo"
        else [("video", page.post_video), ("link", page.post_link)]
    )
    for kind, enabled in kinds:
        if enabled:
            PublishJob.objects.get_or_create(video=video, page=page, kind=kind)


MIN_VIDEO_SCHEDULE_AHEAD = timedelta(minutes=10)
# shortcut: Page rejected a 30-day schedule; raise only after a verified longer API schedule.
MAX_VIDEO_SCHEDULE_AHEAD = timedelta(days=29)


def dispatch_job(job, yt, fb, now):
    # Reload instead of trusting a stale caller's consent or state snapshot.
    job = PublishJob.objects.select_related("video__channel__page", "page").get(pk=job.pk)
    if job.state != "pending" or job.remote_id:
        return
    video, page = job.video, job.page
    if not (page.auto_publish and video.channel.enabled and video.channel.ownership_confirmed):
        return
    if video.baseline or video.channel.page_id != page.pk or not video.rights_confirmed:
        return
    gates = {"video": page.post_video, "photo": page.post_photo, "link": page.post_link}
    if not gates.get(job.kind):
        return
    if job.kind != "photo" and not (video.file_matches_video and video.original):
        return
    scheduled_at = None
    if job.scheduled_at and job.scheduled_at > now:
        if not now + MIN_VIDEO_SCHEDULE_AHEAD <= job.scheduled_at <= now + MAX_VIDEO_SCHEDULE_AHEAD:
            return
        scheduled_at = job.scheduled_at
    try:
        current = yt.details([video.pk], video.channel.channel_id)
        if video.pk in current and not isinstance(current[video.pk].get("title"), str):
            raise ValueError("invalid_source_metadata")
    except Exception:
        PublishJob.objects.filter(pk=job.pk).update(
            error_code="source_check_failed", updated_at=now
        )
        return
    if video.pk not in current:
        Video.objects.filter(pk=video.pk).update(
            available=False, title="", thumbnail_url="", source_checked_at=now
        )
        PublishJob.objects.filter(pk=job.pk).update(
            state=PublishJob.State.BLOCKED,
            error_code="source_not_public",
            updated_at=now,
        )
        return
    try:
        if video.landscape_confirmed:
            route = "photo"
        else:
            if not video.original or not video.file_matches_video:
                raise ValueError("orientation_unconfirmed")
            route = media.route_for_geometry(*media.probe(video.original.path))
        if route != ("video" if job.kind == "link" else job.kind):
            raise ValueError("route_changed")
    except (ValueError, OSError):
        PublishJob.objects.filter(pk=job.pk).update(
            state="blocked", error_code="media_recheck_failed", updated_at=now
        )
        return
    video.title = current[video.pk]["title"]
    video.thumbnail_url = current[video.pk].get("thumbnail_url", "")
    Video.objects.filter(pk=video.pk).update(
        title=video.title, thumbnail_url=video.thumbnail_url, available=True, source_checked_at=now
    )
    if job.kind == "photo" and not valid_thumbnail_url(video.thumbnail_url):
        PublishJob.objects.filter(pk=job.pk).update(
            error_code="thumbnail_unavailable", updated_at=now
        )
        return
    changed = PublishJob.objects.filter(pk=job.pk, state="pending", remote_id="").update(
        state="sending", updated_at=now
    )
    if not changed:
        return
    try:
        if job.kind == "video":
            args = (video.original.path, video.title, f"{video.title}\n{video.youtube_url}")
            remote_id = (
                fb.publish_video(*args, scheduled_at=scheduled_at)
                if scheduled_at
                else fb.publish_video(*args)
            )
        elif job.kind == "photo":
            remote_id = fb.publish_photo(landscape_message(video.title), video.thumbnail_url)
        else:
            remote_id = fb.publish_link(video.title, video.youtube_url)
        pattern = r"[0-9]+" if job.kind == "video" else re.escape(page.page_id) + r"_[0-9]+"
        if (
            not isinstance(remote_id, str)
            or len(remote_id) > 100
            or not re.fullmatch(pattern, remote_id)
        ):
            raise ValueError("invalid_remote_id")
    except Exception as exc:
        # Never resend an ambiguous POST, even when the provider returned a 5xx.
        error_code = str(exc)
        if not re.fullmatch(
            r"facebook_(?:http_\d{3}(?:_code_\d{1,10})?(?:_subcode_\d{1,10})?|api_error(?:_code_\d{1,10})?(?:_subcode_\d{1,10})?|request_failed|invalid_response)",
            error_code,
        ):
            error_code = "post_outcome_unknown"
        # Pause the full Page queue only on Meta's 368 posting block; other
        # failures stay needs_review and the queue keeps going.
        if _meta_posting_block(error_code):
            Page.objects.filter(pk=page.pk).update(auto_publish=False)
        PublishJob.objects.filter(pk=job.pk).update(
            state="needs_review", error_code=error_code, updated_at=now
        )
        return
    # If persistence fails here, 'sending' survives and recovery requires review.
    PublishJob.objects.filter(pk=job.pk).update(
        remote_id=remote_id, state="verifying", error_code="", retry_at=now, updated_at=now
    )


VERIFY_DELAYS = (60, 300, 900, 3600, 21600)


def safe_remote_url(url):
    if not isinstance(url, str) or len(url) > 2000 or any(ord(c) <= 32 for c in url):
        return False
    try:
        value = urlsplit(url)
        return (
            value.scheme == "https"
            and value.hostname in {"facebook.com", "www.facebook.com", "m.facebook.com"}
            and value.username is None
            and value.password is None
            and value.port in {None, 443}
        )
    except ValueError:
        return False


def mark_video_published_if_complete(job):
    """Mark an asset published after every configured delivery job is verified."""
    if job.state != "succeeded":
        return False
    jobs = PublishJob.objects.filter(video_id=job.video_id, page_id=job.page_id)
    if not jobs.exists() or jobs.exclude(state="succeeded").exists():
        return False
    Video.objects.filter(pk=job.video_id).update(state=Video.State.PUBLISHED)
    return True


def delete_verified_video_original(job):
    """Delete the local original after every Page delivery is verified or scheduled."""
    job = PublishJob.objects.select_related("video").get(pk=job.pk)
    done_states = {PublishJob.State.SUCCEEDED, PublishJob.State.SCHEDULED}
    if job.state not in done_states or job.kind not in {"video", "link"}:
        return False
    video = job.video
    video_job = PublishJob.objects.filter(
        video=video, page=job.page, kind="video", state__in=done_states
    )
    all_jobs = PublishJob.objects.filter(video=video, page=job.page)
    if not video_job.exists() or all_jobs.exclude(state__in=done_states).exists():
        return False
    name = video.original.name
    if name:
        try:
            video.original.storage.delete(name)
            Video.objects.filter(pk=video.pk, original=name).update(original="")
        except OSError:
            video_job.update(error_code="original_cleanup_failed")
            return False
    video_job.filter(error_code="original_cleanup_failed").update(error_code="")
    if job.state == PublishJob.State.SUCCEEDED:
        mark_video_published_if_complete(job)
    return True


def verify_job(job, fb, now):
    job = PublishJob.objects.get(pk=job.pk)
    if (
        job.state not in {PublishJob.State.VERIFYING, PublishJob.State.SCHEDULED}
        or not job.remote_id
        or (job.retry_at and job.retry_at > now)
    ):
        return
    if job.state == PublishJob.State.SCHEDULED and job.scheduled_at and job.scheduled_at > now:
        return
    verifying_schedule = (
        job.state == PublishJob.State.VERIFYING
        and job.kind == PublishJob.Kind.VIDEO
        and job.scheduled_at
        and job.scheduled_at > now
    )
    try:
        if verifying_schedule:
            if fb.verify_scheduled_video(job.remote_id, job.scheduled_at):
                job.state = PublishJob.State.SCHEDULED
                job.error_code = ""
                job.retry_at = None
                job.verify_attempts = 0
                job.save(
                    update_fields=[
                        "state",
                        "error_code",
                        "retry_at",
                        "verify_attempts",
                        "updated_at",
                    ]
                )
                Video.objects.filter(pk=job.video_id).update(state=Video.State.SCHEDULED)
                delete_verified_video_original(job)
                return
            url = None
        else:
            url = fb.verify(job.remote_id, job.kind)
    except Exception:
        url = None
    if url and safe_remote_url(url):
        job.state, job.remote_url, job.error_code, job.retry_at = "succeeded", url, "", None
    elif job.verify_attempts >= len(VERIFY_DELAYS):
        job.state, job.error_code, job.retry_at = "needs_review", "verification_exhausted", None
    else:
        job.retry_at = now + timedelta(seconds=VERIFY_DELAYS[job.verify_attempts])
        job.verify_attempts += 1
        job.error_code = "verification_pending"
    job.save(
        update_fields=[
            "state",
            "remote_url",
            "error_code",
            "retry_at",
            "verify_attempts",
            "updated_at",
        ]
    )
    if job.state == "needs_review" and _meta_posting_block(job.error_code):
        Page.objects.filter(pk=job.page_id).update(auto_publish=False)
    if job.state == "succeeded":
        mark_video_published_if_complete(job)
        delete_verified_video_original(job)
