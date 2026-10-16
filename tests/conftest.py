import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from social.models import Channel, Page, Video


def pytest_configure(config):
    # Keep disposable test artifacts out of the OS temp folder.
    scratch = Path(os.getenv("LOCALAPPDATA", str(config.rootpath))) / "hermes" / "cache" / "scratch"
    if not scratch.is_dir():
        scratch = Path(config.rootpath) / ".runtime" / "test-temp"
    if not config.option.basetemp:
        config.option.basetemp = str(scratch / f"katy404-pytest-{os.getpid()}")


@pytest.fixture
def bundle(db, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.BASE_DIR = tmp_path
    page = Page.objects.create(page_id="123", name="Test", auto_publish=True)
    channel = Channel.objects.create(
        channel_id="UC" + "a" * 22, page=page, enabled=True, ownership_confirmed=True
    )
    video = Video.objects.create(
        video_id="a" * 11,
        channel=channel,
        title="clip",
        rights_confirmed=True,
        file_matches_video=True,
    )
    video.original.save(
        "original.mp4", SimpleUploadedFile("original.mp4", b"fixture-not-real-video")
    )
    return SimpleNamespace(page=page, channel=channel, video=video)
