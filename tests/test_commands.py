from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from social.facebook import Facebook
from social.locking import worker_lock
from social.models import PublishJob, Video
from social.youtube import YouTube


def test_worker_sends_then_verifies_and_does_not_duplicate(bundle, monkeypatch):
    monkeypatch.setenv("LIVE_PUBLISH", "1")
    monkeypatch.setenv("YOUTUBE_API_KEY", "fixture")
    monkeypatch.setenv("FB_PAGE_TOKEN_MAIN", "fixture")
    monkeypatch.setattr("social.media.probe", lambda _: (1080, 1920, 30))
    monkeypatch.setattr(YouTube, "details", lambda *a: {bundle.video.pk: {"title": "clip"}})
    sent = []

    def send(*a):
        sent.append(a)
        return "456"

    monkeypatch.setattr(Facebook, "publish_video", send)
    monkeypatch.setattr(Facebook, "verify", lambda *a: "https://www.facebook.com/watch/?v=456")
    for _ in range(3):
        call_command("process_jobs", publish=True, limit=1)
    job = PublishJob.objects.get()
    assert len(sent) == 1 and job.state == "succeeded"


def test_crash_recovery_never_posts_unknown_outcome(bundle, monkeypatch):
    monkeypatch.setenv("LIVE_PUBLISH", "1")
    monkeypatch.setenv("YOUTUBE_API_KEY", "fixture")
    monkeypatch.setenv("FB_PAGE_TOKEN_MAIN", "fixture")
    job = PublishJob.objects.create(
        video=bundle.video, page=bundle.page, kind="video", state="sending"
    )
    monkeypatch.setattr(Facebook, "publish_video", lambda *a: pytest.fail("must not resend"))
    monkeypatch.setattr("social.media.probe", lambda _: (1080, 1920, 30))
    call_command("process_jobs", publish=True)
    job.refresh_from_db()
    assert job.state == "needs_review"


def test_busy_worker_skips_without_network(bundle, monkeypatch):
    monkeypatch.setenv("LIVE_PUBLISH", "1")
    out = StringIO()
    with worker_lock():
        call_command("process_jobs", publish=True, stdout=out)
    assert "worker_busy" in out.getvalue()


def test_scanner_baselines_and_skips_same_day(bundle, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "fixture")
    calls = []

    def snapshot(*a):
        calls.append(a)
        return {bundle.video.pk: {"title": "old"}}

    monkeypatch.setattr(YouTube, "snapshot", snapshot)
    call_command("scan_channels")
    call_command("scan_channels")
    assert len(calls) == 1
    bundle.video.refresh_from_db()
    assert bundle.video.baseline
    call_command("scan_channels", force=True)
    assert len(calls) == 2


def test_preview_has_no_side_effects(bundle, monkeypatch, settings):
    before = list(Video.objects.values())
    out = StringIO()
    call_command("process_jobs", stdout=out)
    assert "preview" in out.getvalue()
    assert list(Video.objects.values()) == before
    assert not PublishJob.objects.exists()
    assert not (settings.BASE_DIR / ".runtime").exists()


def test_global_gate_precedes_writes(bundle, monkeypatch):
    monkeypatch.setenv("LIVE_PUBLISH", "0")
    job = PublishJob.objects.create(
        video=bundle.video, page=bundle.page, kind="video", state="sending"
    )
    with pytest.raises(CommandError, match="live_publish_disabled"):
        call_command("process_jobs", publish=True)
    job.refresh_from_db()
    assert job.state == "sending"


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_invalid_worker_limit_rejected_without_writes(bundle, monkeypatch, limit):
    monkeypatch.setenv("LIVE_PUBLISH", "1")
    with pytest.raises(CommandError, match="limit_must"):
        call_command("process_jobs", publish=True, limit=limit)
