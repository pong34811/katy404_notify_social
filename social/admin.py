"""Staff-only operational UI. Publication is only performed by commands."""

from typing import ClassVar

from django import forms
from django.contrib import admin
from filelock import Timeout

from .locking import worker_lock
from .media import MAX_BYTES
from .models import Channel, Page, PublishJob, Video


class PrivateFileInput(forms.ClearableFileInput):
    template_name = "social/private_file_widget.html"

    def value_from_datadict(self, data, files, name):
        # A forged clear checkbox must not bypass the private widget policy.
        return forms.FileInput.value_from_datadict(self, data, files, name)


class VideoForm(forms.ModelForm):
    class Meta:
        model = Video
        fields = ("original", "rights_confirmed", "file_matches_video", "landscape_confirmed")
        widgets: ClassVar[dict] = {"original": PrivateFileInput()}

    def clean_original(self):
        original = self.cleaned_data.get("original")
        # Only inspect a new upload's cheap attributes; existing files may be absent.
        # ffprobe and network checks belong exclusively in the worker.
        if (
            "original" in self.files
            and original
            and (not 0 < original.size <= MAX_BYTES or not original.name.lower().endswith(".mp4"))
        ):
            raise forms.ValidationError("Use a nonempty MP4 within the 250 MiB size limit.")
        return original

    def clean(self):
        data = super().clean()
        changed_media = {"original", "landscape_confirmed"}.intersection(self.changed_data)
        if (
            not self.instance._state.adding
            and changed_media
            and self.instance.publishjob_set.exclude(
                state__in=[PublishJob.State.PENDING, PublishJob.State.BLOCKED]
            ).exists()
        ):
            raise forms.ValidationError(
                "Delivery already started; resolve the existing job before editing media."
            )
        if "original" in self.files:
            for field in ("rights_confirmed", "file_matches_video"):
                if not data.get(field):
                    self.add_error(
                        field, "Confirm rights and that this new original matches the video."
                    )
        # Revocations on an existing attachment are always permitted.
        return data


class OperationalAdmin(admin.ModelAdmin):
    actions = None

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method != "POST":
            return super().changeform_view(request, object_id, form_url, extra_context)
        # Acquire before Django reads the object/chooses readonly fields and retain
        # through validation, file saving, transaction commit and audit logging.
        lock = worker_lock()
        try:
            lock.acquire()
        except Timeout:
            request._social_worker_busy = True
            return super().changeform_view(request, object_id, form_url, extra_context)
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        finally:
            lock.release()

    def get_form(self, request, obj=None, change=False, **kwargs):
        form_class = super().get_form(request, obj, change=change, **kwargs)
        if not getattr(request, "_social_worker_busy", False):
            return form_class

        class BusyForm(form_class):
            def clean(self):
                super().clean()
                raise forms.ValidationError(
                    "worker_busy: A worker is active. Nothing was saved; retry after it finishes."
                )

        return BusyForm

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Page)
class PageAdmin(OperationalAdmin):
    list_display = (
        "name",
        "page_id",
        "auto_publish",
        "post_video",
        "post_photo",
        "post_link",
        "token_env",
    )

    def get_readonly_fields(self, request, obj=None):
        return ("page_id",) if obj else ()

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name in {"page_id", "token_env"}:
            field.strip = False
            for validator in db_field.validators:
                if validator not in field.validators:
                    field.validators.append(validator)
        return field


@admin.register(Channel)
class ChannelAdmin(OperationalAdmin):
    list_display = (
        "channel_id",
        "page",
        "enabled",
        "ownership_confirmed",
        "baseline_at",
        "last_scan_at",
    )
    readonly_fields = ("baseline_at", "last_scan_at")

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (("channel_id", "page") if obj and obj.baseline_at else ())

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "channel_id":
            field.strip = False
            for validator in db_field.validators:
                if validator not in field.validators:
                    field.validators.append(validator)
        return field


@admin.register(Video)
class VideoAdmin(OperationalAdmin):
    form = VideoForm
    list_display = ("video_id", "title", "channel", "state", "available", "first_seen_at")
    list_filter = ("state", "available", "baseline", "channel")
    search_fields = ("video_id", "title")
    exclude = ("thumbnail_url", "checked_name")
    readonly_fields = (
        "video_id",
        "channel",
        "title",
        "delivery_kind",
        "first_seen_at",
        "source_checked_at",
        "available",
        "baseline",
        "state",
        "prepared_at",
        "inspected_kind",
        "media_error",
        "thumbnail_status",
        "youtube_url",
    )

    @admin.display(description="Thumbnail URL")
    def thumbnail_status(self, obj):
        # Metadata can contain query tokens: never render a raw URL or fetch it here.
        return "Thumbnail metadata present (not displayed)" if obj.thumbnail_url else "No thumbnail"

    def has_add_permission(self, request):
        return False


@admin.register(PublishJob)
class JobAdmin(OperationalAdmin):
    list_display = (
        "id",
        "video",
        "page",
        "kind",
        "scheduled_at",
        "state",
        "remote_id",
        "error_code",
        "updated_at",
    )
    list_filter = ("state", "kind", "page")
    search_fields = ("video__video_id", "remote_id")
    exclude = ("remote_url",)
    readonly_fields = tuple(f.name for f in PublishJob._meta.fields if f.name != "remote_url") + (
        "remote_url_status",
    )

    @admin.display(description="Remote URL")
    def remote_url_status(self, obj):
        return (
            "Recorded (hidden; locate the exact remote ID on Facebook)"
            if obj.remote_url
            else "Not recorded"
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
