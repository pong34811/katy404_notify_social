import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_upgrade_invalidates_legacy_probe_cache():
    executor = MigrationExecutor(connection)
    latest_targets = executor.loader.graph.leaf_nodes()
    old_target = [("social", "0001_initial")]
    try:
        executor.migrate(old_target)
        old_apps = executor.loader.project_state(old_target).apps
        Page = old_apps.get_model("social", "Page")
        Channel = old_apps.get_model("social", "Channel")
        Video = old_apps.get_model("social", "Video")
        page = Page.objects.create(page_id="123", name="Legacy")
        channel = Channel.objects.create(channel_id="UC" + "a" * 22, page=page)
        Video.objects.create(
            video_id="a" * 11,
            channel=channel,
            original="originals/aaaaaaaaaaa/original.mp4",
            checked_name="originals/aaaaaaaaaaa/original.mp4",
            delivery_kind="video",
        )

        new_target = [("social", "0002_video_inspected_kind")]
        executor = MigrationExecutor(connection)
        executor.migrate(new_target)
        new_apps = executor.loader.project_state(new_target).apps
        upgraded = new_apps.get_model("social", "Video").objects.get(pk="a" * 11)
        assert upgraded.checked_name == ""
        assert upgraded.inspected_kind == ""
    finally:
        MigrationExecutor(connection).migrate(latest_targets)
