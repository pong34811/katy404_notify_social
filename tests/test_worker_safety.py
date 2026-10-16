import pytest
from django.core.management import call_command

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

    prepare_video(bundle.video)
    second = Video.objects.create(
        video_id="b" * 11,
        channel=bundle.channel,
        original=bundle.video.original.name,
        rights_confirmed=True,
        file_matches_video=True,
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


def test_preparation_batch_reaches_video_101(bundle, enabled_worker):
    bundle.video.original = ""
    bundle.video.save()
    Video.objects.bulk_create(
        [Video(video_id=f"{index:011d}", channel=bundle.channel) for index in range(100)]
    )
    call_command("process_jobs", publish=True)
    assert Video.objects.filter(prepared_at__isnull=False).count() == 100
    call_command("process_jobs", publish=True)
    assert Video.objects.filter(prepared_at__isnull=False).count() == 101


def test_page_gate_cannot_be_bypassed_by_flag_alone(bundle, monkeypatch, enabled_worker):
    bundle.page.auto_publish = False
    bundle.page.save()
    monkeypatch.setattr(Facebook, "publish_video", lambda *a: pytest.fail("Page is disabled"))
    call_command("process_jobs", publish=True)
    assert not PublishJob.objects.exclude(state="pending").exists()
