"""Real ffmpeg/ffprobe + real ORM/commands; provider HTTP responses are test fixtures."""

import json
import shutil
import subprocess
from urllib.parse import parse_qs, urlsplit

import imageio_ffmpeg
import pytest
import responses
from django.core.files import File
from django.core.management import call_command

from social.models import PublishJob, Video


@responses.activate
def test_real_original_complete_offline_publishing_lifecycle(bundle, monkeypatch, tmp_path):
    if not shutil.which("ffprobe"):
        pytest.skip("Install ffprobe to run real-media acceptance")
    original = tmp_path / "portrait.mp4"
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=90x160:r=24",
            "-t",
            "0.25",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(original),
        ],
        check=True,
        capture_output=True,
    )
    monkeypatch.setenv("YOUTUBE_API_KEY", "fixture")
    monkeypatch.setenv("FB_PAGE_TOKEN_MAIN", "fixture")
    monkeypatch.setenv("LIVE_PUBLISH", "1")
    ids = ["a" * 11]
    thumbnail = "https://i.ytimg.com/vi/ccccccccccc/hqdefault.jpg"
    responses.get(
        "https://www.googleapis.com/youtube/v3/channels",
        json={
            "items": [
                {
                    "id": bundle.channel.channel_id,
                    "contentDetails": {"relatedPlaylists": {"uploads": "playlist"}},
                }
            ]
        },
    )

    def playlist(request):
        return 200, {}, json.dumps({"items": [{"contentDetails": {"videoId": vid}} for vid in ids]})

    def details(request):
        requested = parse_qs(urlsplit(request.url).query)["id"][0].split(",")
        return (
            200,
            {},
            json.dumps(
                {
                    "items": [
                        {
                            "id": vid,
                            "snippet": {
                                "channelId": bundle.channel.channel_id,
                                "title": "ชื่อคลิป " + vid,
                                "liveBroadcastContent": "none",
                                "thumbnails": {"high": {"url": thumbnail}},
                            },
                            "status": {"privacyStatus": "public"},
                        }
                        for vid in requested
                    ]
                }
            ),
        )

    responses.add_callback(
        responses.GET, "https://www.googleapis.com/youtube/v3/playlistItems", callback=playlist
    )
    responses.add_callback(
        responses.GET, "https://www.googleapis.com/youtube/v3/videos", callback=details
    )
    call_command("scan_channels", force=True)
    assert not PublishJob.objects.exists()
    ids.extend(["b" * 11, "c" * 11])
    call_command("scan_channels", force=True)
    vertical = Video.objects.get(pk="b" * 11)
    vertical.rights_confirmed = vertical.file_matches_video = True
    with original.open("rb") as handle:
        vertical.original.save("portrait.mp4", File(handle), save=False)
    vertical.save()
    horizontal = Video.objects.get(pk="c" * 11)
    horizontal.landscape_confirmed = horizontal.rights_confirmed = True
    horizontal.save()
    responses.post("https://graph-video.facebook.com/v26.0/123/videos", json={"id": "456"})
    responses.post(
        "https://graph.facebook.com/v26.0/123/photos", json={"id": "789", "post_id": "123_789"}
    )
    responses.get(
        "https://graph.facebook.com/v26.0/456",
        json={
            "id": "456",
            "from": {"id": "123"},
            "source": "https://video.example/test-fixture.mp4",
        },
    )
    responses.get(
        "https://graph.facebook.com/v26.0/123_789",
        json={
            "id": "123_789",
            "from": {"id": "123"},
            "permalink_url": "https://www.facebook.com/123_789",
        },
    )
    for _ in range(3):
        call_command("process_jobs", publish=True)
    assert PublishJob.objects.count() == 2
    assert set(PublishJob.objects.values_list("state", flat=True)) == {"succeeded"}
    posts = [c for c in responses.calls if c.request.method == "POST"]
    assert len(posts) == 2
    photo = next(c for c in posts if c.request.url.endswith("/photos"))
    assert json.loads(photo.request.body) == {
        "message": "ชื่อคลิป " + "c" * 11 + "\ntag: #katy404 #vtuberth #short #วีทูปเบอร์ไทย",
        "url": thumbnail,
        "published": True,
    }
    assert not horizontal.original
    call_command("scan_channels", force=True)
    call_command("process_jobs", publish=True)
    assert len([c for c in responses.calls if c.request.method == "POST"]) == 2
