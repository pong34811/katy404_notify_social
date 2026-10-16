import pytest
from django.contrib import admin
from django.urls import reverse

from social.models import Channel, Page, PublishJob, Video

pytestmark = pytest.mark.django_db


@pytest.fixture
def video(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.BASE_DIR = tmp_path
    page = Page.objects.create(page_id="123", name="Test")
    channel = Channel.objects.create(channel_id="UC" + "a" * 22, page=page)
    return Video.objects.create(video_id="a" * 11, channel=channel)


def video_url(video):
    return reverse("admin:social_video_change", args=[video.pk])


def test_admin_rejects_whitespace_in_literal_identifiers(rf, admin_client):
    from django.core.exceptions import ValidationError

    page_admin = admin.site._registry[Page]
    channel_admin = admin.site._registry[Channel]
    request = rf.get("/admin/")
    from django.contrib.auth.models import AnonymousUser

    request.user = AnonymousUser()
    page_form = page_admin.get_form(request)
    channel_form = channel_admin.get_form(request)
    for form, field_name, value in (
        (page_form, "page_id", " 123 "),
        (page_form, "token_env", " FB_PAGE_TOKEN_MAIN "),
        (channel_form, "channel_id", " UC" + "a" * 22 + " "),
    ):
        assert form.base_fields[field_name].strip is False
        try:
            form.base_fields[field_name].clean(value)
        except ValidationError:
            continue
        pytest.fail(f"{field_name} accepted whitespace-padded literal: {value!r}")


def test_identity_fields_are_immutable_in_admin(admin_client, video):
    from django.utils import timezone

    page = video.channel.page
    response = admin_client.post(
        reverse("admin:social_page_change", args=[page.pk]),
        {
            "name": "renamed",
            "page_id": "999",
            "token_env": "FB_PAGE_TOKEN_MAIN",
        },
    )
    assert response.status_code == 302
    page.refresh_from_db()
    assert page.page_id == "123"
    channel = video.channel
    channel.baseline_at = timezone.now()
    channel.save()
    other = Page.objects.create(page_id="456", name="other")
    response = admin_client.post(
        reverse("admin:social_channel_change", args=[channel.pk]),
        {
            "channel_id": "UC" + "b" * 22,
            "page": other.pk,
            "baseline_at": "",
            "last_scan_at": "",
            "enabled": "on",
        },
    )
    assert response.status_code == 302
    channel.refresh_from_db()
    assert channel.channel_id == "UC" + "a" * 22
    assert channel.page_id == page.pk
    assert channel.baseline_at is not None


def test_source_metadata_and_private_storage_never_render_raw(admin_client, video):
    from django.core.files.uploadedfile import SimpleUploadedFile

    video.original.save("private-name.mp4", SimpleUploadedFile("private-name.mp4", b"fixture"))
    video.checked_name = video.original.name
    video.thumbnail_url = "https://i.ytimg.com/x.jpg?access_token=must-not-render"
    video.save()
    response = admin_client.get(video_url(video))
    assert response.status_code == 200
    html = response.content.decode()
    assert "Private original attached" in html
    assert video.original.name not in html
    assert str(video.original.path) not in html
    assert "must-not-render" not in html
    assert "/private-media/" not in html
    assert 'name="original-clear"' not in html
    form = response.context["adminform"].form
    assert set(form.fields) == {
        "original",
        "rights_confirmed",
        "file_matches_video",
        "landscape_confirmed",
    }


@pytest.mark.parametrize(
    "extension,size", [(".txt", 10), (".mp4", 0), (".mp4", 250 * 1024 * 1024 + 1)]
)
def test_invalid_original_rejected_without_reading_network(admin_client, video, extension, size):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from social.admin import VideoForm

    original = SimpleUploadedFile("clip" + extension, b"fixture")
    original.size = size
    form = VideoForm(
        data={"rights_confirmed": True, "file_matches_video": True},
        files={"original": original},
        instance=video,
    )
    assert not form.is_valid()
    assert "original" in form.errors


@pytest.mark.parametrize("missing", ["rights_confirmed", "file_matches_video"])
def test_new_upload_requires_both_confirmations(admin_client, video, missing):
    from django.core.files.uploadedfile import SimpleUploadedFile

    payload = {
        "original": SimpleUploadedFile("clip.mp4", b"not-real-media"),
        "rights_confirmed": "on",
        "file_matches_video": "on",
    }
    payload.pop(missing)
    response = admin_client.post(video_url(video), payload)
    assert response.status_code == 200
    assert response.context["adminform"].form.errors
    video.refresh_from_db()
    assert not video.original


def test_upload_only_saves_file_and_landscape_needs_no_original(admin_client, video):
    from django.core.files.uploadedfile import SimpleUploadedFile

    response = admin_client.post(
        video_url(video),
        {
            "original": SimpleUploadedFile("clip.mp4", b"not-real-media"),
            "rights_confirmed": "on",
            "file_matches_video": "on",
        },
    )
    assert response.status_code == 302
    video.refresh_from_db()
    assert video.original
    assert not PublishJob.objects.exists()
    video.original.delete(save=True)
    response = admin_client.post(
        video_url(video),
        {
            "landscape_confirmed": "on",
            "rights_confirmed": "on",
        },
    )
    assert response.status_code == 302
    video.refresh_from_db()
    assert video.landscape_confirmed and not video.original
    assert not PublishJob.objects.exists()


@pytest.mark.parametrize("state", ["sending", "verifying", "succeeded", "needs_review"])
def test_media_cannot_change_after_delivery_but_rights_can_be_revoked(admin_client, video, state):
    from django.core.files.uploadedfile import SimpleUploadedFile

    PublishJob.objects.create(video=video, page=video.channel.page, kind="video", state=state)
    video.rights_confirmed = video.file_matches_video = True
    video.save()
    for change in (
        {"landscape_confirmed": "on"},
        {"original": SimpleUploadedFile("replacement.mp4", b"fixture")},
    ):
        response = admin_client.post(
            video_url(video),
            {
                "rights_confirmed": "on",
                "file_matches_video": "on",
                **change,
            },
        )
        assert response.status_code == 200
        assert response.context["adminform"].form.non_field_errors()
    response = admin_client.post(video_url(video), {})
    assert response.status_code == 302
    video.refresh_from_db()
    assert not video.rights_confirmed and not video.file_matches_video
    assert not video.landscape_confirmed and not video.original


@pytest.mark.parametrize("model_name", ["page", "channel", "video"])
def test_worker_busy_is_a_form_error_without_any_mutation(admin_client, video, model_name):
    from social.locking import worker_lock

    obj = {"page": video.channel.page, "channel": video.channel, "video": video}[model_name]
    url = reverse(f"admin:social_{model_name}_change", args=[obj.pk])
    before = type(obj).objects.values().get(pk=obj.pk)
    payload = {
        "name": "changed",
        "token_env": "FB_PAGE_TOKEN_MAIN",
        "enabled": "on",
        "channel_id": obj.channel_id if model_name == "channel" else "",
        "page": video.channel.page_id,
        "landscape_confirmed": "on",
        "rights_confirmed": "on",
    }
    with worker_lock():
        response = admin_client.post(url, payload)
    assert response.status_code == 200
    assert "worker_busy" in str(response.context["adminform"].form.non_field_errors())
    assert type(obj).objects.values().get(pk=obj.pk) == before


def test_worker_lock_covers_saving_not_only_validation(admin_client, video, monkeypatch):
    from filelock import Timeout

    from social.locking import worker_lock

    model_admin = admin.site._registry[Video]
    original_save = model_admin.save_model
    checked = []

    def save(*args, **kwargs):
        with pytest.raises(Timeout), worker_lock():
            pass
        checked.append(True)
        return original_save(*args, **kwargs)

    monkeypatch.setattr(model_admin, "save_model", save)
    assert admin_client.post(video_url(video), {"rights_confirmed": "on"}).status_code == 302
    assert checked == [True]


def test_get_admin_does_not_acquire_worker_lock(admin_client, video, settings):
    assert admin_client.get(video_url(video)).status_code == 200
    assert not (settings.BASE_DIR / ".runtime").exists()


def test_forged_clear_checkbox_does_not_delete_private_original(admin_client, video):
    from django.core.files.uploadedfile import SimpleUploadedFile

    video.original.save("clip.mp4", SimpleUploadedFile("clip.mp4", b"fixture"))
    name = video.original.name
    response = admin_client.post(video_url(video), {"original-clear": "on"})
    assert response.status_code == 302
    video.refresh_from_db()
    assert video.original.name == name


def test_job_is_view_only_and_does_not_render_untrusted_remote_url(admin_client, video):
    job = PublishJob.objects.create(
        video=video,
        page=video.channel.page,
        kind="photo",
        remote_url="https://www.facebook.com/post?access_token=must-not-render",
    )
    url = reverse("admin:social_publishjob_change", args=[job.pk])
    response = admin_client.get(url)
    assert response.status_code == 200
    assert "must-not-render" not in response.content.decode()
    assert admin_client.post(url, {"state": "pending", "remote_id": "999"}).status_code == 403
    job.refresh_from_db()
    assert not job.remote_id


def test_csrf_is_enforced_for_admin_writes(admin_user, video):
    from django.test import Client

    client = Client(enforce_csrf_checks=True)
    client.force_login(admin_user)
    response = client.post(video_url(video), {"rights_confirmed": "on"})
    assert response.status_code == 403
    video.refresh_from_db()
    assert not video.rights_confirmed


def test_forged_readonly_fields_do_not_change_delivery_identity(admin_client, video):
    before = Video.objects.values().get(pk=video.pk)
    response = admin_client.post(
        video_url(video),
        {
            "video_id": "b" * 11,
            "channel": "999",
            "title": "tampered",
            "state": "ready",
            "baseline": "on",
            "thumbnail_url": "https://example.invalid",
            "delivery_kind": "video",
        },
    )
    assert response.status_code == 302
    assert Video.objects.values().get(pk=video.pk) == before


def test_missing_stored_file_does_not_prevent_revocation(admin_client, video):
    video.original = "originals/missing.mp4"
    video.rights_confirmed = video.file_matches_video = True
    video.save()
    response = admin_client.post(video_url(video), {})
    assert response.status_code == 302
    video.refresh_from_db()
    assert not video.rights_confirmed and not video.file_matches_video


def test_admin_requires_staff_and_media_is_private(client, django_user_model):
    url = reverse("admin:social_video_changelist")
    assert "/admin/login/" in client.get(url).url
    user = django_user_model.objects.create_user("ordinary")
    client.force_login(user)
    assert "/admin/login/" in client.get(url).url
    assert client.get("/private-media/originals/anything.mp4").status_code == 404


def test_delivery_records_cannot_be_added_deleted_or_bulk_deleted(rf, admin_user):
    request = rf.get("/admin/")
    request.user = admin_user
    for model in (Video, PublishJob):
        model_admin = admin.site._registry[model]
        assert not model_admin.has_add_permission(request)
        assert not model_admin.has_delete_permission(request)
        assert "delete_selected" not in model_admin.get_actions(request)
    assert not admin.site._registry[PublishJob].has_change_permission(request)
