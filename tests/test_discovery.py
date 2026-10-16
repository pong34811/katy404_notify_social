from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from social.models import PublishJob, Video


def test_complete_baseline_then_new_upload(bundle):
    from social.services import scan_channel

    # Fixture record is treated as already observed during baseline, not delivered.
    api = SimpleNamespace(snapshot=lambda _: {"a" * 11: {"title": "old"}})
    scan_channel(bundle.channel, api, timezone.now())
    bundle.video.refresh_from_db()
    assert bundle.video.baseline
    assert not PublishJob.objects.exists()
    api.snapshot = lambda _: {"a" * 11: {"title": "edited"}, "b" * 11: {"title": "new"}}
    scan_channel(bundle.channel, api, timezone.now())
    assert Video.objects.count() == 2
    assert Video.objects.get(pk="a" * 11).title == "edited"
    assert not Video.objects.get(pk="b" * 11).baseline
    assert not PublishJob.objects.exists()


def test_incomplete_snapshot_does_not_initialize(bundle):
    from social.services import scan_channel

    def fail(_):
        raise RuntimeError("snapshot_page_limit")

    with pytest.raises(RuntimeError):
        scan_channel(bundle.channel, SimpleNamespace(snapshot=fail), timezone.now())
    bundle.channel.refresh_from_db()
    assert bundle.channel.baseline_at is None
    assert bundle.channel.last_scan_at is None


def test_missing_source_purges_metadata_and_return_does_not_duplicate(bundle):
    from social.services import scan_channel

    scan_channel(bundle.channel, SimpleNamespace(snapshot=lambda _: {}), timezone.now())
    bundle.video.refresh_from_db()
    assert not bundle.video.available and not bundle.video.title and not bundle.video.thumbnail_url
    scan_channel(
        bundle.channel,
        SimpleNamespace(snapshot=lambda _: {"a" * 11: {"title": "back"}}),
        timezone.now(),
    )
    assert Video.objects.count() == 1
    bundle.video.refresh_from_db()
    assert bundle.video.available


def test_stale_source_titles_are_removed_from_admin_audit(bundle):
    from django.contrib.admin.models import CHANGE, LogEntry
    from django.contrib.auth import get_user_model
    from django.contrib.contenttypes.models import ContentType

    from social.services import purge_stale_source_metadata

    user = get_user_model().objects.create_superuser(username="retention", password="fixture")
    bundle.video.title = "SOURCE_METADATA_RETENTION_SENTINEL"
    bundle.video.source_checked_at = timezone.now() - timedelta(days=31)
    bundle.video.save()
    LogEntry.objects.create(
        user=user,
        content_type=ContentType.objects.get_for_model(Video),
        object_id=bundle.video.pk,
        object_repr=str(bundle.video),
        action_flag=CHANGE,
    )
    purge_stale_source_metadata(timezone.now())
    bundle.video.refresh_from_db()
    audit = LogEntry.objects.get(object_id=bundle.video.pk)
    assert not bundle.video.title
    assert audit.object_repr != "SOURCE_METADATA_RETENTION_SENTINEL"
    assert audit.object_repr == "Expired video metadata"


def test_stale_source_metadata_is_purged(bundle):
    from social.services import purge_stale_source_metadata

    now = timezone.now()
    Video.objects.filter(pk=bundle.video.pk).update(
        source_checked_at=now - timedelta(days=31), thumbnail_url="https://i.ytimg.com/test.jpg"
    )
    purge_stale_source_metadata(now)
    bundle.video.refresh_from_db()
    assert not bundle.video.title and not bundle.video.thumbnail_url and not bundle.video.available
