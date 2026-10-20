from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from social.models import Video


@pytest.fixture
def fresh(bundle, monkeypatch):
    """A new public clip with no original, with the download feature switched on."""
    bundle.video.original.delete(save=False)
    Video.objects.filter(pk=bundle.video.pk).update(
        original="", rights_confirmed=False, file_matches_video=False, state="waiting_file"
    )
    bundle.video.refresh_from_db()
    monkeypatch.setenv("YT_DOWNLOAD", "1")
    return bundle


def fake_dl(info=(1080, 1920, 30), written=b"mp4-bytes", fail=False):
    calls = SimpleNamespace(info=0, download=0)

    def get_info(video_id):
        calls.info += 1
        if fail:
            raise RuntimeError("boom")
        return info

    def download(video_id, dest_dir):
        calls.download += 1
        path = dest_dir / f"{video_id}.mp4"
        path.write_bytes(written)
        return path

    return SimpleNamespace(info=get_info, download=download, calls=calls)


def test_vertical_clip_is_downloaded_and_bound(fresh):
    from social.services import fetch_original

    dl = fake_dl()
    assert fetch_original(fresh.video, dl, timezone.now()) is True
    fresh.video.refresh_from_db()
    assert fresh.video.original.name.endswith(".mp4")
    assert fresh.video.rights_confirmed and fresh.video.file_matches_video
    assert dl.calls.download == 1


def test_horizontal_clip_is_not_downloaded(fresh):
    from social.services import fetch_original

    dl = fake_dl(info=(1920, 1080, 60))
    fetch_original(fresh.video, dl, timezone.now())
    fresh.video.refresh_from_db()
    assert not fresh.video.original
    assert fresh.video.landscape_confirmed and fresh.video.rights_confirmed
    assert dl.calls.download == 0


def test_disabled_by_default(fresh, monkeypatch):
    from social.services import fetch_original

    monkeypatch.delenv("YT_DOWNLOAD")
    dl = fake_dl()
    assert fetch_original(fresh.video, dl, timezone.now()) is False
    assert dl.calls.info == 0


@pytest.mark.parametrize(
    "field,value", [("baseline", True), ("available", False), ("landscape_confirmed", True)]
)
def test_skips_ineligible_video(fresh, field, value):
    from social.services import fetch_original

    setattr(fresh.video, field, value)
    fresh.video.save()
    dl = fake_dl()
    assert fetch_original(fresh.video, dl, timezone.now()) is False
    assert dl.calls.info == 0


def test_skips_unowned_channel_or_manual_page(fresh):
    from social.services import fetch_original

    fresh.channel.ownership_confirmed = False
    fresh.channel.save()
    dl = fake_dl()
    assert fetch_original(fresh.video, dl, timezone.now()) is False
    fresh.channel.ownership_confirmed = True
    fresh.channel.save()
    fresh.page.auto_publish = False
    fresh.page.save()
    fresh.video.refresh_from_db()
    assert fetch_original(fresh.video, dl, timezone.now()) is False
    assert dl.calls.info == 0


def test_failure_is_recorded_and_backed_off(fresh):
    from social.services import fetch_original

    now = timezone.now()
    assert fetch_original(fresh.video, fake_dl(fail=True), now) is False
    fresh.video.refresh_from_db()
    assert fresh.video.media_error == "download_failed"
    assert not fresh.video.original
    dl = fake_dl()
    assert fetch_original(fresh.video, dl, now + timedelta(minutes=5)) is False
    assert dl.calls.info == 0
    assert fetch_original(fresh.video, dl, now + timedelta(hours=2)) is True


def test_oversized_download_is_discarded(fresh, monkeypatch):
    from social import media
    from social.services import fetch_original

    monkeypatch.setattr(media, "MAX_BYTES", 4)
    assert fetch_original(fresh.video, fake_dl(written=b"123456789"), timezone.now()) is False
    fresh.video.refresh_from_db()
    assert not fresh.video.original and fresh.video.media_error == "download_failed"


def test_prepare_video_routes_downloaded_original(fresh, monkeypatch):
    from social.services import fetch_original, prepare_video

    monkeypatch.setattr("social.media.probe", lambda _: (1080, 1920, 30))
    fetch_original(fresh.video, fake_dl(), timezone.now())
    fresh.video.refresh_from_db()
    prepare_video(fresh.video)
    fresh.video.refresh_from_db()
    assert fresh.video.state == "ready" and fresh.video.delivery_kind == "video"


def test_ytdlp_command_has_no_cookies_and_bounds_size(tmp_path, monkeypatch):
    from social import downloader

    seen = []

    def fake_run(cmd, **kw):
        seen.append((cmd, kw))
        (tmp_path / "bbbbbbbbbbb.mp4").write_bytes(b"x")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(downloader.subprocess, "run", fake_run)
    path = downloader.download("bbbbbbbbbbb", tmp_path)
    cmd, kw = seen[0]
    assert path == tmp_path / "bbbbbbbbbbb.mp4"
    assert "--no-playlist" in cmd and "--max-filesize" in cmd
    assert not any("cookies" in part for part in cmd)
    assert cmd[-1] == "https://www.youtube.com/watch?v=bbbbbbbbbbb"
    assert kw["shell"] is False and kw["timeout"] > 0


def test_ytdlp_rejects_bad_video_id(tmp_path):
    from social import downloader

    with pytest.raises(downloader.DownloadError):
        downloader.download("--exec=calc", tmp_path)


def test_worker_prepares_video_in_same_pass_after_download(fresh, monkeypatch):
    from social import downloader
    from social.models import PublishJob
    from social.worker import process_queue

    monkeypatch.setenv("YOUTUBE_API_KEY", "fixture")
    monkeypatch.setattr("social.media.probe", lambda _: (1080, 1920, 30))
    monkeypatch.setattr(downloader, "info", fake_dl().info)
    monkeypatch.setattr(downloader, "download", fake_dl().download)
    PublishJob.objects.create(
        video=fresh.video,
        page=fresh.page,
        kind="video",
        scheduled_at=timezone.now() + timedelta(days=1),
    )
    process_queue(1)
    assert PublishJob.objects.filter(video=fresh.video, kind="video").exists()
