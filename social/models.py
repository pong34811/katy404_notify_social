"""Only metadata is persisted here; originals stay in private file storage."""

import uuid
from pathlib import Path

from django.db import models

from .validators import (
    channel_id_validator,
    page_id_validator,
    token_env_validator,
    video_id_validator,
)


def original_path(instance, filename):
    return f"originals/{instance.video_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"


class Page(models.Model):
    page_id = models.CharField(max_length=40, unique=True, validators=[page_id_validator])
    name = models.CharField(max_length=200)
    token_env = models.CharField(
        max_length=100, default="FB_PAGE_TOKEN_MAIN", validators=[token_env_validator]
    )
    auto_publish = models.BooleanField(default=False)
    post_video = models.BooleanField(default=True)
    post_photo = models.BooleanField(default=True)
    post_link = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class Channel(models.Model):
    channel_id = models.CharField(max_length=24, unique=True, validators=[channel_id_validator])
    page = models.ForeignKey(Page, on_delete=models.PROTECT)
    enabled = models.BooleanField(default=False)
    ownership_confirmed = models.BooleanField(default=False)
    baseline_at = models.DateTimeField(null=True, blank=True)
    last_scan_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.channel_id


class Video(models.Model):
    class State(models.TextChoices):
        BASELINE = "baseline", "Baseline (not queued)"
        WAITING_FILE = "waiting_file", "Waiting for original or landscape confirmation"
        WAITING_RIGHTS = "waiting_rights", "Waiting for rights confirmation"
        WAITING_THUMBNAIL = "waiting_thumbnail", "Waiting for thumbnail"
        READY = "ready", "Ready for video upload"
        READY_PHOTO = "ready_photo", "Ready for photo notification"
        REJECTED = "rejected", "Unsupported media"
        NEEDS_REVIEW = "needs_review", "Route changed: needs review"
        PUBLISHED = "published", "All configured Facebook deliveries verified"

    video_id = models.CharField(primary_key=True, max_length=11, validators=[video_id_validator])
    channel = models.ForeignKey(Channel, on_delete=models.PROTECT)
    title = models.CharField(max_length=500, blank=True)
    thumbnail_url = models.URLField(max_length=2000, blank=True)
    landscape_confirmed = models.BooleanField(
        default=False, help_text="Confirm from the actual video or Studio, never its thumbnail."
    )
    delivery_kind = models.CharField(max_length=10, blank=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    source_checked_at = models.DateTimeField(null=True, blank=True)
    available = models.BooleanField(default=True)
    baseline = models.BooleanField(default=False)
    original = models.FileField(upload_to=original_path, blank=True, max_length=500)
    rights_confirmed = models.BooleanField(
        default=False,
        help_text="Confirm rights to republish video/audio or its thumbnail on Facebook.",
    )
    file_matches_video = models.BooleanField(default=False)
    state = models.CharField(max_length=30, choices=State.choices, default=State.WAITING_FILE)
    checked_name = models.CharField(max_length=500, blank=True)
    inspected_kind = models.CharField(max_length=10, blank=True, editable=False)
    prepared_at = models.DateTimeField(null=True, blank=True)
    media_error = models.CharField(max_length=100, blank=True)
    download_attempted_at = models.DateTimeField(null=True, blank=True, editable=False)

    @property
    def youtube_url(self):
        return f"https://www.youtube.com/watch?v={self.video_id}"

    def __str__(self):
        # Django Admin retains object_repr in LogEntry; never duplicate source titles there.
        return self.video_id


class PublishJob(models.Model):
    class Kind(models.TextChoices):
        VIDEO = "video", "Video"
        PHOTO = "photo", "Landscape thumbnail notification"
        LINK = "link", "Optional vertical link post"

    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        SENDING = "sending", "Sending"
        VERIFYING = "verifying", "Verifying"
        SUCCEEDED = "succeeded", "Remote object verified (visibility requires manual check)"
        NEEDS_REVIEW = "needs_review", "Needs review; do not resend"
        BLOCKED = "blocked", "Blocked"

    video = models.ForeignKey(Video, on_delete=models.PROTECT)
    page = models.ForeignKey(Page, on_delete=models.PROTECT)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    state = models.CharField(max_length=20, choices=State.choices, default=State.PENDING)
    remote_id = models.CharField(max_length=100, blank=True)
    remote_url = models.URLField(max_length=2000, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    verify_attempts = models.PositiveIntegerField(default=0)
    attempted_at = models.DateTimeField(null=True, blank=True)
    retry_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["video", "page", "kind"], name="unique_delivery"),
            models.UniqueConstraint(
                fields=["video", "page"],
                condition=models.Q(kind__in=["video", "photo"]),
                name="unique_primary_delivery",
            ),
        ]

    def __str__(self):
        return f"{self.video_id}: {self.kind} / {self.state}"
