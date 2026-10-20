import os
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from social.models import PublishJob, Video

THUMB = "https://i.ytimg.com/vi/aaaaaaaaaaa/hqdefault.jpg"


def test_readback_retries_get_only_then_succeeds(bundle):
    from social.services import verify_job

    job = PublishJob.objects.create(
        video=bundle.video, page=bundle.page, kind="video", state="verifying", remote_id="456"
    )
    now = timezone.now()
    calls = []

    def check(*args):
        calls.append(args)
        return None

    fb = SimpleNamespace(verify=check)
    verify_job(job, fb, now)
    job.refresh_from_db()
    assert job.retry_at == now + timedelta(seconds=60)
    verify_job(job, fb, now + timedelta(seconds=30))
    assert len(calls) == 1
    fb.verify = lambda *a: "https://www.facebook.com/watch/?v=456"
    verify_job(job, fb, job.retry_at)
    job.refresh_from_db()
    assert job.state == "succeeded" and job.remote_id == "456"


def test_readback_exhaustion_preserves_id_for_manual_review(bundle):
    from social.services import verify_job

    job = PublishJob.objects.create(
        video=bundle.video, page=bundle.page, kind="photo", state="verifying", remote_id="123_456"
    )
    fb = SimpleNamespace(verify=lambda *a: None)
    now = timezone.now()
    for _ in range(6):
        verify_job(job, fb, now)
        job.refresh_from_db()
        now = job.retry_at or now
    assert job.state == "needs_review" and job.remote_id == "123_456"


def test_readback_rejects_nonfacebook_url(bundle):
    from social.services import verify_job

    job = PublishJob.objects.create(
        video=bundle.video, page=bundle.page, kind="photo", state="verifying", remote_id="123_456"
    )
    verify_job(job, SimpleNamespace(verify=lambda *a: "https://evil.example/"), timezone.now())
    job.refresh_from_db()
    assert job.state != "succeeded" and not job.remote_url


def _api(bundle):
    return SimpleNamespace(
        details=lambda *a: {bundle.video.pk: {"title": "ชื่อคลิป", "thumbnail_url": THUMB}}
    )


def test_photo_dispatch_exact_caption_and_no_duplicate(bundle, monkeypatch):
    from social.services import dispatch_job, prepare_video

    bundle.video.original.delete(save=True)
    bundle.video.landscape_confirmed, bundle.video.thumbnail_url = True, THUMB
    bundle.video.save()
    prepare_video(bundle.video)
    sent = []

    def photo(*args):
        sent.append(args)
        return "123_456"

    fb = SimpleNamespace(
        publish_photo=photo,
        publish_video=lambda *a: pytest.fail("must not upload landscape video"),
        publish_link=lambda *a: pytest.fail("must not create another link post"),
    )
    monkeypatch.setattr("social.media.probe", lambda _: pytest.fail("no original required"))
    job = PublishJob.objects.get()
    dispatch_job(job, _api(bundle), fb, timezone.now())
    # Deliberately pass the stale pending instance twice.
    dispatch_job(job, _api(bundle), fb, timezone.now())
    job.refresh_from_db()
    assert sent == [("ชื่อคลิป\ntag: #katy404 #vtuberth #short #วีทูปเบอร์ไทย", THUMB)]
    assert job.state == "verifying" and job.remote_id == "123_456"


def test_ambiguous_video_post_never_reposts(bundle, monkeypatch):
    from social.services import dispatch_job, prepare_video

    monkeypatch.setattr("social.media.probe", lambda _: (1080, 1920, 30))
    prepare_video(bundle.video)
    calls = []

    def send(*args):
        calls.append(args)
        raise TimeoutError("secret-body-must-not-leak")

    fb = SimpleNamespace(publish_video=send)
    job = PublishJob.objects.get()
    dispatch_job(job, _api(bundle), fb, timezone.now())
    dispatch_job(job, _api(bundle), fb, timezone.now())
    job.refresh_from_db()
    assert len(calls) == 1
    assert job.state == "needs_review" and job.error_code == "post_outcome_unknown"


@pytest.mark.parametrize(
    "cause", ["private", "source_error", "rights", "page", "channel", "file", "landscape"]
)
def test_changed_source_or_consent_stops_dispatch(bundle, monkeypatch, cause):
    from social.services import dispatch_job, prepare_video

    monkeypatch.setattr("social.media.probe", lambda _: (1080, 1920, 30))
    prepare_video(bundle.video)
    job = PublishJob.objects.get()
    yt = _api(bundle)
    if cause == "private":
        yt.details = lambda *a: {}
    elif cause == "source_error":

        def fail(*a):
            raise RuntimeError("private error")

        yt.details = fail
    elif cause == "rights":
        Video.objects.filter(pk=bundle.video.pk).update(rights_confirmed=False)
    elif cause == "page":
        bundle.page.auto_publish = False
        bundle.page.save()
    elif cause == "channel":
        bundle.channel.enabled = False
        bundle.channel.save()
    elif cause == "file":
        bundle.video.original.delete(save=True)
    else:
        monkeypatch.setattr("social.media.probe", lambda _: (1920, 1080, 30))
    fb = SimpleNamespace(publish_video=lambda *a: pytest.fail("must not POST"))
    dispatch_job(job, yt, fb, timezone.now())
    job.refresh_from_db()
    assert not job.remote_id


def test_vertical_preparation_is_idempotent(bundle, monkeypatch):
    from social.services import prepare_video

    monkeypatch.setattr("social.media.probe", lambda _: (1080, 1920, 30))
    prepare_video(bundle.video)
    prepare_video(bundle.video)
    assert list(PublishJob.objects.values_list("kind", flat=True)) == ["video"]
    bundle.video.refresh_from_db()
    assert bundle.video.state == "ready"


def test_landscape_photo_needs_no_original(bundle, monkeypatch):
    from social.services import prepare_video

    bundle.video.original.delete(save=True)
    bundle.video.landscape_confirmed = True
    bundle.video.thumbnail_url = THUMB
    bundle.video.save()
    bundle.page.post_link = True
    bundle.page.save()
    monkeypatch.setattr("social.media.probe", lambda _: pytest.fail("no original needed"))
    prepare_video(bundle.video)
    prepare_video(bundle.video)
    assert list(PublishJob.objects.values_list("kind", flat=True)) == ["photo"]
    bundle.video.refresh_from_db()
    assert bundle.video.state == "ready_photo"


@pytest.mark.parametrize(
    "field,value,want",
    [
        ("rights_confirmed", False, "waiting_rights"),
        ("file_matches_video", False, "waiting_rights"),
        ("original", "", "waiting_file"),
        ("baseline", True, "waiting_file"),
        ("available", False, "waiting_file"),
    ],
)
def test_unapproved_or_missing_input_is_not_queued(bundle, monkeypatch, field, value, want):
    from social.services import prepare_video

    setattr(bundle.video, field, value)
    bundle.video.save()
    monkeypatch.setattr(
        "social.media.probe", lambda _: pytest.fail("must not inspect unapproved media")
    )
    prepare_video(bundle.video)
    assert not PublishJob.objects.exists()
    if field not in {"baseline", "available"}:
        assert bundle.video.state == want


@pytest.mark.parametrize(
    "geometry,expected",
    [((1920, 1080, 60), "photo"), ((1080, 1080, 180), "video"), ((1080, 1080, 181), None)],
)
def test_geometry_routes_without_duplicate_primary(bundle, monkeypatch, geometry, expected):
    from social.services import prepare_video

    bundle.video.thumbnail_url = THUMB
    bundle.video.save()
    monkeypatch.setattr("social.media.probe", lambda _: geometry)
    prepare_video(bundle.video)
    assert list(PublishJob.objects.values_list("kind", flat=True)) == (
        [expected] if expected else []
    )


def test_manual_landscape_confirmation_does_not_overwrite_inspected_route(bundle, monkeypatch):
    from social.services import prepare_video

    bundle.page.post_video = False
    bundle.page.post_photo = False
    bundle.page.save()
    monkeypatch.setattr("social.media.probe", lambda _: (1080, 1920, 30))
    prepare_video(bundle.video)
    bundle.video.refresh_from_db()
    assert bundle.video.inspected_kind == "video"
    bundle.video.landscape_confirmed = True
    bundle.video.thumbnail_url = THUMB
    bundle.video.save()
    prepare_video(bundle.video)
    bundle.video.refresh_from_db()
    assert bundle.video.delivery_kind == "photo"
    assert bundle.video.inspected_kind == "video"
    bundle.video.landscape_confirmed = False
    bundle.video.save()
    bundle.page.post_video = bundle.page.post_photo = True
    bundle.page.save()
    prepare_video(bundle.video)
    bundle.video.refresh_from_db()
    assert bundle.video.delivery_kind == "video"
    assert list(PublishJob.objects.values_list("kind", flat=True)) == ["video"]


def test_failed_probe_retries_same_original_after_ffprobe_recovers(bundle, monkeypatch):
    from social.services import prepare_video

    def fail(_):
        raise ValueError("ffprobe_unavailable")

    monkeypatch.setattr("social.media.probe", fail)
    prepare_video(bundle.video)
    bundle.video.refresh_from_db()
    assert not bundle.video.inspected_kind
    assert bundle.video.checked_name != bundle.video.original.name
    assert bundle.video.state == "rejected"
    monkeypatch.setattr("social.media.probe", lambda _: (1080, 1920, 30))
    prepare_video(bundle.video)
    bundle.video.refresh_from_db()
    assert bundle.video.state == "ready"
    assert PublishJob.objects.filter(video=bundle.video, kind="video").exists()


def test_missing_thumbnail_waits_and_route_change_does_not_duplicate(bundle, monkeypatch):
    from social.services import prepare_video

    monkeypatch.setattr("social.media.probe", lambda _: (1080, 1920, 30))
    prepare_video(bundle.video)
    bundle.video.landscape_confirmed = True
    bundle.video.thumbnail_url = THUMB
    bundle.video.save()
    prepare_video(bundle.video)
    assert bundle.video.state == "needs_review"
    assert list(PublishJob.objects.values_list("kind", flat=True)) == ["video"]


def test_original_is_deleted_only_after_verified_video_post(bundle):
    from social.services import verify_job

    original_path = bundle.video.original.path
    assert os.path.exists(original_path)
    job = PublishJob.objects.create(
        video=bundle.video,
        page=bundle.page,
        kind="video",
        state="verifying",
        remote_id="456",
        retry_at=timezone.now(),
    )
    fb = SimpleNamespace(verify=lambda *args: "https://www.facebook.com/watch/?v=456")

    verify_job(job, fb, timezone.now())

    job.refresh_from_db()
    bundle.video.refresh_from_db()
    assert job.state == "succeeded"
    assert not bundle.video.original
    assert not os.path.exists(original_path)


def test_unverified_video_post_keeps_original(bundle):
    from social.services import verify_job

    original_path = bundle.video.original.path
    job = PublishJob.objects.create(
        video=bundle.video,
        page=bundle.page,
        kind="video",
        state="verifying",
        remote_id="456",
        retry_at=timezone.now(),
    )
    fb = SimpleNamespace(verify=lambda *args: None)

    verify_job(job, fb, timezone.now())

    bundle.video.refresh_from_db()
    assert os.path.exists(original_path)
    assert bundle.video.original.name


def test_cleanup_batch_respects_worker_limit_before_dispatch(bundle, monkeypatch):
    from social.worker import process_queue

    bundle.page.auto_publish = True
    bundle.page.save()
    cleanup_video = bundle.video
    cleanup_video.baseline = True
    cleanup_video.save()
    cleanup_job = PublishJob.objects.create(
        video=cleanup_video,
        page=bundle.page,
        kind="video",
        state="succeeded",
        remote_id="456",
        error_code="original_cleanup_failed",
    )
    pending_video = Video.objects.create(
        video_id="b" * 11,
        channel=bundle.channel,
        title="next",
        rights_confirmed=True,
        file_matches_video=True,
    )
    PublishJob.objects.create(
        video=pending_video,
        page=bundle.page,
        kind="video",
        scheduled_at=timezone.now() - timedelta(minutes=1),
    )
    from django.core.files.base import ContentFile

    pending_video.original.save("next.mp4", ContentFile(b"fixture"))
    monkeypatch.setenv("LIVE_PUBLISH", "1")
    monkeypatch.setenv("YOUTUBE_API_KEY", "fixture")
    monkeypatch.setenv("FB_PAGE_TOKEN_MAIN", "fixture")
    monkeypatch.setattr("social.media.probe", lambda _: (1080, 1920, 30))
    posted = []
    monkeypatch.setattr(
        "social.worker.YouTube",
        lambda _: SimpleNamespace(
            details=lambda *args: {pending_video.pk: {"title": "next", "thumbnail_url": THUMB}}
        ),
    )
    fb = SimpleNamespace(publish_video=lambda *args: posted.append(args) or "789")
    monkeypatch.setattr("social.worker.Facebook", lambda *args: fb)

    result = process_queue(1)

    cleanup_job.refresh_from_db()
    assert result == "processed=1"
    assert cleanup_job.error_code == ""
    cleanup_video.refresh_from_db()
    assert not cleanup_video.original
    assert not posted
    assert PublishJob.objects.get(video=pending_video).state == "pending"


def test_failed_original_cleanup_retries_without_republishing(bundle, monkeypatch):
    from social.services import delete_verified_video_original

    original_path = bundle.video.original.path
    storage = bundle.video.original.storage
    real_delete = storage.delete
    job = PublishJob.objects.create(
        video=bundle.video,
        page=bundle.page,
        kind="video",
        state="succeeded",
        remote_id="456",
    )

    def fail_delete(name):
        raise PermissionError("temporary file lock")

    monkeypatch.setattr(storage, "delete", fail_delete)
    assert not delete_verified_video_original(job)
    job.refresh_from_db()
    bundle.video.refresh_from_db()
    assert job.state == "succeeded" and job.error_code == "original_cleanup_failed"
    assert bundle.video.original.name and os.path.exists(original_path)

    monkeypatch.setattr(storage, "delete", real_delete)
    assert delete_verified_video_original(job)
    job.refresh_from_db()
    bundle.video.refresh_from_db()
    assert job.state == "succeeded" and not job.error_code
    assert not bundle.video.original and not os.path.exists(original_path)


def test_original_waits_until_all_delivery_kinds_are_verified(bundle):
    from social.services import verify_job

    original_path = bundle.video.original.path
    bundle.page.post_link = True
    bundle.page.save()
    video_job = PublishJob.objects.create(
        video=bundle.video,
        page=bundle.page,
        kind="video",
        state="verifying",
        remote_id="456",
        retry_at=timezone.now(),
    )
    link_job = PublishJob.objects.create(
        video=bundle.video,
        page=bundle.page,
        kind="link",
        state="verifying",
        remote_id="123_456",
        retry_at=timezone.now(),
    )
    now = timezone.now()
    verify_job(
        video_job, SimpleNamespace(verify=lambda *a: "https://www.facebook.com/watch/?v=456"), now
    )
    bundle.video.refresh_from_db()
    assert os.path.exists(original_path)
    assert bundle.video.original.name
    verify_job(link_job, SimpleNamespace(verify=lambda *a: "https://www.facebook.com/123_456"), now)
    link_job.refresh_from_db()
    bundle.video.refresh_from_db()
    assert link_job.state == "succeeded"
    assert bundle.video.state == "published"
    assert not bundle.video.original
    assert not os.path.exists(original_path)


def test_published_video_is_not_prepared_or_requeued(bundle, monkeypatch):
    from social.services import prepare_video

    bundle.video.state = "published"
    bundle.video.original = ""
    bundle.video.save()
    monkeypatch.setattr(
        "social.media.probe", lambda *_: pytest.fail("published video must not be reprobed")
    )
    prepare_video(bundle.video)
    assert bundle.video.state == "published"
    assert not PublishJob.objects.exists()


def test_successful_link_post_does_not_delete_video_original(bundle):
    from social.services import verify_job

    original_path = bundle.video.original.path
    job = PublishJob.objects.create(
        video=bundle.video,
        page=bundle.page,
        kind="link",
        state="verifying",
        remote_id="123_456",
        retry_at=timezone.now(),
    )
    fb = SimpleNamespace(verify=lambda *args: "https://www.facebook.com/123_456")

    verify_job(job, fb, timezone.now())

    job.refresh_from_db()
    bundle.video.refresh_from_db()
    assert job.state == "succeeded"
    assert bundle.video.original.name
    assert os.path.exists(original_path)
