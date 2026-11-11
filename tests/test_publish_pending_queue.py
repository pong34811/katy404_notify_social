import hashlib
import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command

from social.models import PublishJob, Video


def make_pending(bundle, video_id=None):
    video = bundle.video
    if video_id:
        video = Video.objects.create(
            video_id=video_id,
            channel=bundle.channel,
            title="clip",
            rights_confirmed=True,
            file_matches_video=True,
        )
        video.original.save(
            "original.mp4",
            SimpleUploadedFile("original.mp4", Path(bundle.video.original.path).read_bytes()),
        )
    video.state = Video.State.READY
    video.inspected_kind = "video"
    video.delivery_kind = "video"
    video.save()
    return PublishJob.objects.create(video=video, page=bundle.page, kind=PublishJob.Kind.VIDEO)


def prepare_fixture(monkeypatch, settings, tmp_path, bundle):
    settings.BASE_DIR = tmp_path
    (tmp_path / ".env").write_text("LIVE_PUBLISH=0\n", encoding="utf-8")
    monkeypatch.setattr("social.media.probe", lambda _: (1080, 1920, 30))
    return make_pending(bundle)


def test_default_preview_is_read_only(bundle, monkeypatch, settings, tmp_path):
    job = prepare_fixture(monkeypatch, settings, tmp_path, bundle)
    before = list(PublishJob.objects.values_list("pk", "state", "remote_id"))
    out = StringIO()

    call_command("publish_pending_queue", page_id="123", limit=1, stdout=out)

    assert "preview page=123 pending=1 requested=1" in out.getvalue()
    assert list(PublishJob.objects.values_list("pk", "state", "remote_id")) == before
    assert PublishJob.objects.get(pk=job.pk).state == PublishJob.State.PENDING
    assert not (tmp_path / ".runtime").exists()


def test_preview_accepts_one_minute_interval(bundle, monkeypatch, settings, tmp_path):
    prepare_fixture(monkeypatch, settings, tmp_path, bundle)
    out = StringIO()

    call_command("publish_pending_queue", page_id="123", limit=1, interval=60, stdout=out)

    assert "preview page=123 pending=1 requested=1" in out.getvalue()


def test_backup_copies_and_hashes_the_exact_target(bundle, monkeypatch, settings, tmp_path):
    job = prepare_fixture(monkeypatch, settings, tmp_path, bundle)
    bundle.page.auto_publish = False
    bundle.page.save(update_fields=["auto_publish"])

    call_command("publish_pending_queue", page_id="123", limit=1, backup=True)

    backup = tmp_path / ".runtime" / "backups" / "facebook-batch-2026-10-21"
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["jobs"][0]
    saved = backup / entry["filename"]
    assert entry["job_id"] == job.pk
    assert saved.read_bytes() == Path(job.video.original.path).read_bytes()
    assert hashlib.sha256(saved.read_bytes()).hexdigest() == entry["sha256"]


def test_publish_requires_global_gate_and_rejects_unverified_targets(
    bundle, monkeypatch, settings, tmp_path
):
    prepare_fixture(monkeypatch, settings, tmp_path, bundle)
    monkeypatch.setenv("LIVE_PUBLISH", "0")

    with pytest.raises(CommandError, match="live_publish_disabled"):
        call_command("publish_pending_queue", page_id="123", limit=1, publish=True)

    PublishJob.objects.all().update(state=PublishJob.State.BLOCKED)
    with pytest.raises(CommandError, match="target_count_or_readiness_mismatch"):
        call_command("publish_pending_queue", page_id="123", limit=1, publish=True)


def test_batch_stops_if_another_post_still_needs_readback(bundle, monkeypatch, settings, tmp_path):
    prepare_fixture(monkeypatch, settings, tmp_path, bundle)
    other = make_pending(bundle, "b" * 11)
    other.state = PublishJob.State.VERIFYING
    other.remote_id = "456"
    other.save(update_fields=["state", "remote_id"])
    bundle.page.auto_publish = False
    bundle.page.save(update_fields=["auto_publish"])
    call_command("publish_pending_queue", page_id="123", limit=1, backup=True)
    (tmp_path / ".env").write_text("LIVE_PUBLISH=1\n", encoding="utf-8")
    monkeypatch.setenv("LIVE_PUBLISH", "1")
    monkeypatch.setattr(
        "social.management.commands.publish_pending_queue.sys.stdin",
        SimpleNamespace(isatty=lambda: True),
    )

    with pytest.raises(CommandError, match="unrelated_verification_pending"):
        call_command("publish_pending_queue", page_id="123", limit=1, publish=True)
    assert not bundle.page.__class__.objects.get(pk=bundle.page.pk).auto_publish
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "LIVE_PUBLISH=0\n"


def test_publish_serializes_posts_and_verifies_before_the_next(
    bundle, monkeypatch, settings, tmp_path
):
    first = prepare_fixture(monkeypatch, settings, tmp_path, bundle)
    second = make_pending(bundle, "b" * 11)
    bundle.page.auto_publish = False
    bundle.page.save(update_fields=["auto_publish"])
    call_command("publish_pending_queue", page_id="123", limit=2, backup=True)

    (tmp_path / ".env").write_text("LIVE_PUBLISH=1\n", encoding="utf-8")
    monkeypatch.setenv("LIVE_PUBLISH", "1")
    monkeypatch.setattr(
        "social.management.commands.publish_pending_queue.sys.stdin",
        SimpleNamespace(isatty=lambda: True),
    )
    monkeypatch.setattr("builtins.input", lambda _: "public-ok")
    clock = [0.0]
    sleeps = []
    monkeypatch.setattr(
        "social.management.commands.publish_pending_queue.time.monotonic", lambda: clock[0]
    )

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr("social.management.commands.publish_pending_queue.time.sleep", sleep)
    events = []

    def process_one(limit, include_unscheduled=False, job_ids=None):
        assert limit == 1 and include_unscheduled
        assert bundle.page.__class__.objects.get(pk=bundle.page.pk).auto_publish
        assert (tmp_path / ".env").read_text(encoding="utf-8") == "LIVE_PUBLISH=1\n"
        job = PublishJob.objects.get(pk=job_ids[0])
        events.append((job.pk, job.state, clock[0]))
        if job.state == PublishJob.State.PENDING:
            PublishJob.objects.filter(pk=job.pk).update(
                state=PublishJob.State.VERIFYING, remote_id=f"900{job.pk}"
            )
        else:
            PublishJob.objects.filter(pk=job.pk).update(
                state=PublishJob.State.SUCCEEDED,
                remote_url=f"https://www.facebook.com/watch/?v={job.remote_id}",
            )
        return "processed=1"

    monkeypatch.setattr("social.management.commands.publish_pending_queue.process_queue", process_one)
    out = StringIO()

    call_command("publish_pending_queue", page_id="123", limit=2, publish=True, stdout=out)

    assert [event[:2] for event in events] == [
        (first.pk, PublishJob.State.PENDING),
        (first.pk, PublishJob.State.VERIFYING),
        (second.pk, PublishJob.State.PENDING),
        (second.pk, PublishJob.State.VERIFYING),
    ]
    assert events[2][2] - events[0][2] >= 60
    assert sleeps == [60]
    assert PublishJob.objects.filter(state=PublishJob.State.SUCCEEDED).count() == 2
    assert not bundle.page.__class__.objects.get(pk=bundle.page.pk).auto_publish
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "LIVE_PUBLISH=0\n"
    assert "batch_complete verified=2" in out.getvalue()
