from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from social.facebook import Facebook
from social.models import PublishJob, Video
from social.youtube import YouTube


@pytest.fixture
def enabled_worker(monkeypatch):
    monkeypatch.setenv("LIVE_PUBLISH", "1")
    monkeypatch.setenv("YOUTUBE_API_KEY", "fixture")
    monkeypatch.setenv("FB_PAGE_TOKEN_MAIN", "fixture")
    monkeypatch.setattr("social.media.probe", lambda _: (1080, 1920, 30))


def test_unavailable_oldest_job_does_not_starve_next_job(bundle, monkeypatch, enabled_worker):
    from social.services import prepare_video

    PublishJob.objects.create(
        video=bundle.video,
        page=bundle.page,
        kind="video",
        scheduled_at=timezone.now() - timedelta(minutes=1),
    )
    prepare_video(bundle.video)
    second = Video.objects.create(
        video_id="b" * 11,
        channel=bundle.channel,
        original=bundle.video.original.name,
        rights_confirmed=True,
        file_matches_video=True,
    )
    PublishJob.objects.create(
        video=second,
        page=bundle.page,
        kind="video",
        scheduled_at=timezone.now() - timedelta(minutes=1),
    )
    prepare_video(second)
    calls = []
    monkeypatch.setattr(
        YouTube,
        "details",
        lambda self, ids, channel: (
            {} if ids == [bundle.video.pk] else {second.pk: {"title": "next"}}
        ),
    )
    monkeypatch.setattr(Facebook, "publish_video", lambda *a: calls.append(a) or "789")
    call_command("process_jobs", publish=True, limit=1)
    call_command("process_jobs", publish=True, limit=1)
    assert len(calls) == 1
    assert PublishJob.objects.get(video=second).state == "verifying"


def test_saved_remote_id_recovers_to_get_without_post(bundle, monkeypatch, enabled_worker):
    job = PublishJob.objects.create(
        video=bundle.video, page=bundle.page, kind="video", state="sending", remote_id="456"
    )
    monkeypatch.setattr(Facebook, "verify", lambda *a: "https://www.facebook.com/watch/?v=456")
    monkeypatch.setattr(Facebook, "publish_video", lambda *a: pytest.fail("must not resend"))
    call_command("process_jobs", publish=True)
    job.refresh_from_db()
    assert job.state == "succeeded" and job.remote_id == "456"


def test_worker_checks_verifying_jobs_before_new_posts(bundle, monkeypatch, enabled_worker):
    now = timezone.now()
    verifying = PublishJob.objects.create(
        video=bundle.video,
        page=bundle.page,
        kind="video",
        state=PublishJob.State.VERIFYING,
        remote_id="456",
        scheduled_at=now + timedelta(hours=1),
    )
    pending_video = Video.objects.create(
        video_id="b" * 11,
        channel=bundle.channel,
        original=bundle.video.original.name,
        rights_confirmed=True,
        file_matches_video=True,
    )
    pending = PublishJob.objects.create(
        video=pending_video,
        page=bundle.page,
        kind="video",
        scheduled_at=now - timedelta(minutes=1),
    )
    monkeypatch.setattr("social.worker.fetch_original", lambda *args: False)
    monkeypatch.setattr("social.worker.prepare_video", lambda *args: None)
    monkeypatch.setattr("social.media.probe", lambda _: (1080, 1920, 30))
    monkeypatch.setattr(
        YouTube,
        "details",
        lambda self, ids, channel: {pending_video.pk: {"title": "clip"}},
    )
    checked = []
    posted = []
    monkeypatch.setattr(
        Facebook,
        "verify_scheduled_video",
        lambda *args: checked.append(args) or False,
    )
    monkeypatch.setattr(Facebook, "publish_video", lambda *args: posted.append(args))

    call_command("process_jobs", publish=True, limit=2)

    verifying.refresh_from_db()
    pending.refresh_from_db()
    assert len(checked) == 1 and not posted
    assert verifying.state == PublishJob.State.VERIFYING
    assert pending.state == PublishJob.State.PENDING


def test_preparation_batch_reaches_video_101(bundle, enabled_worker):
    from datetime import timedelta

    bundle.video.original = ""
    bundle.video.save()
    now = timezone.now() - timedelta(minutes=1)
    videos = [Video(video_id=f"{index:011d}", channel=bundle.channel) for index in range(100)]
    Video.objects.bulk_create(videos)
    PublishJob.objects.bulk_create(
        [
            PublishJob(video=video, page=bundle.page, kind="video", scheduled_at=now)
            for video in videos
        ]
    )
    PublishJob.objects.create(video=bundle.video, page=bundle.page, kind="video", scheduled_at=now)
    call_command("process_jobs", publish=True, limit=100)
    assert Video.objects.filter(prepared_at__isnull=False).count() == 100
    call_command("process_jobs", publish=True, limit=100)
    assert Video.objects.filter(prepared_at__isnull=False).count() == 101


def test_worker_prepares_future_scheduled_only_and_does_not_publish_early(
    bundle, monkeypatch, enabled_worker
):
    from django.core.files.base import ContentFile

    from social.youtube import YouTube

    now = timezone.now()
    future_job_time = now + timedelta(hours=1)
    future = Video.objects.create(
        video_id="c" * 11,
        channel=bundle.channel,
        rights_confirmed=True,
        file_matches_video=True,
    )
    future.original.save("future.mp4", ContentFile(b"fixture"))
    PublishJob.objects.create(
        video=future, page=bundle.page, kind="video", scheduled_at=future_job_time
    )
    unscheduled = Video.objects.create(
        video_id="d" * 11,
        channel=bundle.channel,
        rights_confirmed=True,
        file_matches_video=True,
    )
    unscheduled.original.save("unscheduled.mp4", ContentFile(b"fixture"))
    PublishJob.objects.create(video=unscheduled, page=bundle.page, kind="video")
    calls = []

    def schedule(*args, **kwargs):
        calls.append((args, kwargs))
        return "789"

    monkeypatch.setattr(Facebook, "publish_video", schedule)
    monkeypatch.setattr(Facebook, "verify_scheduled_video", lambda *args: True)
    monkeypatch.setattr(
        YouTube, "details", lambda self, ids, channel: {future.pk: {"title": "future"}}
    )
    call_command("process_jobs", publish=True)
    assert calls[0][1]["scheduled_at"] == future_job_time
    assert Video.objects.filter(pk=future.pk, prepared_at__isnull=False).exists()
    assert not Video.objects.filter(pk=unscheduled.pk, prepared_at__isnull=False).exists()
    assert PublishJob.objects.filter(video=future, state="verifying").exists()
    assert PublishJob.objects.filter(video=unscheduled, state="pending").exists()

    call_command("process_jobs", publish=True)
    assert len(calls) == 1
    assert PublishJob.objects.get(video=future).state == "scheduled"
    assert PublishJob.objects.get(video=unscheduled).state == "pending"


def test_page_gate_cannot_be_bypassed_by_flag_alone(bundle, monkeypatch, enabled_worker):
    bundle.page.auto_publish = False
    bundle.page.save()
    monkeypatch.setattr(Facebook, "publish_video", lambda *a: pytest.fail("Page is disabled"))
    call_command("process_jobs", publish=True)
    assert not PublishJob.objects.exclude(state="pending").exists()


@pytest.mark.parametrize(
    "error,paused",
    [
        ("facebook_http_400_code_368_subcode_1390008", True),
        ("facebook_api_error_code_368", True),
        ("facebook_http_400_code_3680", False),
    ],
)
def test_meta_posting_block_stops_remaining_page_uploads(
    bundle, monkeypatch, enabled_worker, error, paused
):
    second = Video.objects.create(
        video_id="b" * 11,
        channel=bundle.channel,
        original=bundle.video.original.name,
        rights_confirmed=True,
        file_matches_video=True,
    )
    scheduled_at = timezone.now() + timedelta(hours=1)
    for video in (bundle.video, second):
        PublishJob.objects.create(
            video=video, page=bundle.page, kind="video", scheduled_at=scheduled_at
        )
    monkeypatch.setattr(YouTube, "details", lambda self, ids, channel: {ids[0]: {"title": "clip"}})
    calls = []

    def blocked(*args, **kwargs):
        calls.append(args)
        raise RuntimeError(error)

    monkeypatch.setattr(Facebook, "publish_video", blocked)
    call_command("process_jobs", publish=True, limit=10)
    call_command("process_jobs", publish=True, limit=10)
    bundle.page.refresh_from_db()
    assert bundle.page.auto_publish == (not paused)
    assert len(calls) == (1 if paused else 2)
    first = PublishJob.objects.get(video=bundle.video)
    assert first.state == "needs_review" and first.error_code == error and not first.remote_id
    assert PublishJob.objects.get(video=second).state == ("pending" if paused else "needs_review")
