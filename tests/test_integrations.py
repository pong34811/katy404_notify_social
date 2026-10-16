from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from social.facebook import Facebook
from social.models import PublishJob
from social.youtube import YouTube


def test_preflight_is_read_only_and_hides_tokens(bundle, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "fixture-key")
    monkeypatch.setenv("FB_PAGE_TOKEN_MAIN", "fixture-token")
    before = list(PublishJob.objects.values())
    monkeypatch.setattr(
        YouTube, "_get", lambda *a, **k: {"items": [{"id": bundle.channel.channel_id}]}
    )
    seen = []

    def get(self, url, **kwargs):
        seen.append(url)

        class Response:
            status_code = 200

            def json(self):
                return {"id": "123", "name": "Test"}

        return Response()

    monkeypatch.setattr("requests.Session.get", get)
    out = StringIO()
    call_command("check_integrations", stdout=out)
    assert "preflight_ok" in out.getvalue() and "fixture-token" not in out.getvalue()
    assert len(seen) == 1 and list(PublishJob.objects.values()) == before


def test_reconcile_reads_existing_object_without_post(bundle, monkeypatch):
    monkeypatch.setenv("FB_PAGE_TOKEN_MAIN", "fixture")
    job = PublishJob.objects.create(
        video=bundle.video, page=bundle.page, kind="photo", state="needs_review"
    )
    monkeypatch.setattr(Facebook, "verify", lambda *a: "https://www.facebook.com/123_456")
    monkeypatch.setattr(Facebook, "publish_photo", lambda *a: pytest.fail("must not POST"))
    out = StringIO()
    call_command("reconcile_job", str(job.pk), remote_id="123_456", stdout=out)
    job.refresh_from_db()
    assert job.state == "succeeded" and job.remote_id == "123_456"
    assert "reconciled_without_publish" in out.getvalue()


def test_reconcile_wrong_owner_or_new_id_does_not_change_job(bundle, monkeypatch):
    monkeypatch.setenv("FB_PAGE_TOKEN_MAIN", "fixture")
    job = PublishJob.objects.create(
        video=bundle.video,
        page=bundle.page,
        kind="photo",
        state="needs_review",
        remote_id="123_456",
    )
    monkeypatch.setattr(Facebook, "verify", lambda *a: pytest.fail("id is immutable"))
    with pytest.raises(CommandError, match="remote_id_is_immutable"):
        call_command("reconcile_job", str(job.pk), remote_id="123_789")
    job.refresh_from_db()
    assert job.state == "needs_review" and job.remote_id == "123_456"
