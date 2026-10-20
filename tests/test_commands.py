from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from social.facebook import Facebook
from social.locking import worker_lock
from social.models import PublishJob, Video
from social.youtube import YouTube


def test_worker_sends_then_verifies_and_does_not_duplicate(bundle, monkeypatch):
    monkeypatch.setenv("LIVE_PUBLISH", "1")
    monkeypatch.setenv("YOUTUBE_API_KEY", "fixture")
    monkeypatch.setenv("FB_PAGE_TOKEN_MAIN", "fixture")
    monkeypatch.setattr("social.media.probe", lambda _: (1080, 1920, 30))
    PublishJob.objects.create(
        video=bundle.video,
        page=bundle.page,
        kind="video",
        scheduled_at=timezone.now() - timedelta(minutes=1),
    )
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


def test_run_scheduler_once_runs_scan_and_process_and_survives_failure(monkeypatch):
    calls = []
    real = call_command

    def fake(name, *a, **kw):
        if name in ("scan_channels", "process_jobs"):
            calls.append((name, kw.get("force"), kw.get("publish")))
            if name == "scan_channels":
                raise RuntimeError("boom")
            return None
        return real(name, *a, **kw)

    monkeypatch.setattr("social.management.commands.run_scheduler.call_command", fake)
    err = StringIO()
    call_command("run_scheduler", once=True, publish=True, stderr=err)
    assert calls == [("scan_channels", True, None), ("process_jobs", None, True)]
    assert "scan_channels_failed RuntimeError" in err.getvalue()


def test_run_scheduler_rejects_short_interval():
    with pytest.raises(CommandError, match="interval_must_be_at_least_60_seconds"):
        call_command("run_scheduler", scan_interval=10, once=True)
