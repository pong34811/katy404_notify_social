import pytest
from django.core.exceptions import ValidationError


@pytest.mark.django_db
def test_delivery_constraints_and_safe_page_defaults():
    from django.db import IntegrityError, transaction

    from social.models import Channel, Page, PublishJob, Video

    page = Page.objects.create(page_id="123", name="Test")
    channel = Channel.objects.create(channel_id="UC" + "a" * 22, page=page)
    video = Video.objects.create(video_id="a" * 11, channel=channel)
    PublishJob.objects.create(video=video, page=page, kind="video")
    for kind in ["video", "photo"]:
        with pytest.raises(IntegrityError), transaction.atomic():
            PublishJob.objects.create(video=video, page=page, kind=kind)
    assert not page.auto_publish and not page.post_link
    assert page.post_photo and page.post_video


def test_literal_identifiers():
    from social.validators import channel_id_validator, video_id_validator

    channel_id_validator("UC" + "a" * 22)
    video_id_validator("a" * 11)
    for invalid in [" UC" + "a" * 22, "@example", "UCshort"]:
        with pytest.raises(ValidationError):
            channel_id_validator(invalid)
