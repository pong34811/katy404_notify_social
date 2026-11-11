import traceback

import pytest
import requests
import responses

BASE = "https://www.googleapis.com/youtube/v3/"
CHANNEL = "UC" + "a" * 22
VIDEO = "a" * 11


@responses.activate
def test_get_reads_json_with_key_and_finite_timeouts(monkeypatch):
    from social.youtube import YouTube

    api = YouTube("fixture-key")
    responses.get(BASE + "channels", json={"items": []})
    real_get = api.session.get
    options = []

    def get(*args, **kwargs):
        options.append(kwargs)
        return real_get(*args, **kwargs)

    monkeypatch.setattr(api.session, "get", get)
    assert api._get("channels", part="id", id=CHANNEL) == {"items": []}
    assert responses.calls[0].request.params["key"] == "fixture-key"
    assert options[0]["timeout"] == (10, 60)


@pytest.mark.parametrize(
    "failure,code",
    [
        (403, "youtube_http_403"),
        (429, "youtube_http_429"),
        (500, "youtube_http_500"),
        ("transport", "youtube_request_failed"),
        ("json", "youtube_invalid_response"),
        ("error", "youtube_api_error"),
        ("list", "youtube_invalid_response"),
    ],
)
@responses.activate
def test_get_sanitizes_provider_failures(failure, code):
    from social.youtube import YouTube

    api = YouTube("fixture-key")
    if isinstance(failure, int):
        responses.get(BASE + "videos", status=failure, body="secret-provider-body")
    elif failure == "transport":
        responses.get(BASE + "videos", body=requests.Timeout("fixture-key secret-provider-body"))
    elif failure == "json":
        responses.get(BASE + "videos", body="fixture-key secret-provider-body")
    else:
        responses.get(
            BASE + "videos", json={"error": "secret-provider-body"} if failure == "error" else []
        )
    with pytest.raises(RuntimeError, match=f"^{code}$") as caught:
        api._get("videos", id=VIDEO)
    output = "".join(traceback.format_exception(caught.value))
    assert "fixture-key" not in output and "secret-provider-body" not in output
    assert len(responses.calls) == 1


@responses.activate
def test_get_never_follows_redirects_or_retries():
    from social.youtube import YouTube

    api = YouTube("fixture-key")
    responses.get(BASE + "channels", status=302, headers={"Location": BASE + "videos"})
    responses.get(BASE + "videos", json={"items": []})
    with pytest.raises(RuntimeError, match="^youtube_http_302$"):
        api._get("channels")
    assert len(responses.calls) == 1
    assert api.session.get_adapter(BASE).max_retries.total == 0


@pytest.mark.parametrize("key", ["", None, "  ", "key\nsecret"])
def test_key_configuration_is_rejected(key):
    from social.youtube import YouTube

    with pytest.raises(ValueError, match="^youtube_key_missing_or_invalid$"):
        YouTube(key)


@pytest.mark.parametrize(
    "resource", ["../videos", "channels?key=secret", "search", "https://evil.example"]
)
def test_get_rejects_resources_outside_read_only_contract(resource):
    from social.youtube import YouTube

    with pytest.raises(ValueError, match="^youtube_resource$"):
        YouTube("fixture-key")._get(resource)


def video_item(vid=VIDEO, **extra):
    return {
        "id": vid,
        "snippet": {
            "channelId": CHANNEL,
            "title": "ชื่อคลิป",
            "liveBroadcastContent": "none",
            "thumbnails": {"high": {"url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"}},
        },
        "status": {"privacyStatus": "public"},
        **extra,
    }


def test_details_batches_fifty_and_returns_public_metadata(monkeypatch):
    from social.youtube import YouTube

    api = YouTube("fixture-key")
    ids = [f"{i:011d}" for i in range(101)]
    calls = []

    def get(resource, **params):
        assert resource == "videos"
        calls.append(params)
        return {"items": [video_item(vid) for vid in params["id"].split(",")]}

    monkeypatch.setattr(api, "_get", get)
    result = api.details(ids, CHANNEL)
    assert set(result) == set(ids)
    assert result[ids[0]] == {
        "title": "ชื่อคลิป",
        "thumbnail_url": f"https://i.ytimg.com/vi/{ids[0]}/hqdefault.jpg",
    }
    assert [len(call["id"].split(",")) for call in calls] == [50, 50, 1]
    assert all(call["maxResults"] == 50 for call in calls)
    assert all(
        call["part"] == "snippet,status,contentDetails,liveStreamingDetails" for call in calls
    )
    assert api.details([], CHANNEL) == {}
    assert len(calls) == 3


@pytest.mark.parametrize(
    "privacy,live,replay,expected",
    [
        ("private", "none", False, {}),
        ("unlisted", "none", False, {}),
        ("public", "live", False, {}),
        ("public", "upcoming", False, {}),
        ("public", "none", True, {VIDEO: {"title": "ชื่อคลิป", "thumbnail_url": f"https://i.ytimg.com/vi/{VIDEO}/hqdefault.jpg"}}),
    ],
)
def test_details_excludes_nonpublic_and_all_streams(monkeypatch, privacy, live, replay, expected):
    from social.youtube import YouTube

    api = YouTube("fixture-key")
    item = video_item(status={"privacyStatus": privacy})
    item["snippet"]["liveBroadcastContent"] = live
    if replay:
        item["liveStreamingDetails"] = {"actualEndTime": "2026-10-15T10:00:00Z"}
    monkeypatch.setattr(api, "_get", lambda *a, **k: {"items": [item]})
    assert api.details([VIDEO], CHANNEL) == expected


@pytest.mark.parametrize("mismatch", ["owner", "id", "duplicate"])
def test_details_rejects_mismatched_or_duplicate_items(monkeypatch, mismatch):
    from social.youtube import YouTube

    api = YouTube("fixture-key")
    item = video_item()
    if mismatch == "owner":
        item["snippet"]["channelId"] = "UC" + "b" * 22
    if mismatch == "id":
        item["id"] = "b" * 11
    monkeypatch.setattr(
        api, "_get", lambda *a, **k: {"items": [item, item] if mismatch == "duplicate" else [item]}
    )
    with pytest.raises(ValueError, match="^(source_channel_mismatch|duplicate_video_item)$"):
        api.details([VIDEO], CHANNEL)


@pytest.mark.parametrize(
    "ids,channel",
    [
        ([" " + VIDEO], CHANNEL),
        ([VIDEO] * 50 + ["bad"], CHANNEL),
        ([VIDEO], " " + CHANNEL),
        ([VIDEO], "@handle"),
    ],
)
def test_details_validates_entire_request_before_http(monkeypatch, ids, channel):
    from django.core.exceptions import ValidationError

    from social.youtube import YouTube

    api = YouTube("fixture-key")
    monkeypatch.setattr(api, "_get", lambda *a, **k: pytest.fail("invalid input reached HTTP"))
    with pytest.raises((ValueError, ValidationError)):
        api.details(ids, channel)


def channel_response(channel=CHANNEL):
    return {
        "items": [{"id": channel, "contentDetails": {"relatedPlaylists": {"uploads": "playlist"}}}]
    }


def test_snapshot_reads_every_page_and_deduplicates_before_details(monkeypatch):
    from social.youtube import YouTube

    api = YouTube("fixture-key")
    calls = []

    def get(resource, **params):
        calls.append((resource, params))
        if resource == "channels":
            return channel_response()
        if resource == "playlistItems":
            assert params["maxResults"] == 50 and params["playlistId"] == "playlist"
            if "pageToken" not in params:
                return {"items": [{"contentDetails": {"videoId": VIDEO}}], "nextPageToken": "next"}
            assert params["pageToken"] == "next"
            return {"items": [{"contentDetails": {"videoId": vid}} for vid in [VIDEO, "b" * 11]]}
        assert params["id"] == VIDEO + "," + "b" * 11
        return {"items": [video_item(vid) for vid in params["id"].split(",")]}

    monkeypatch.setattr(api, "_get", get)
    assert set(api.snapshot(CHANNEL)) == {VIDEO, "b" * 11}
    assert [resource for resource, _ in calls] == [
        "channels",
        "playlistItems",
        "playlistItems",
        "videos",
    ]


@pytest.mark.parametrize("repeat", [True, False])
def test_snapshot_fails_closed_on_repeated_token_or_page_limit(monkeypatch, repeat):
    from social.youtube import YouTube

    api = YouTube("fixture-key")
    pages = []

    def get(resource, **params):
        if resource == "channels":
            return channel_response()
        assert resource == "playlistItems", "partial snapshot must not reach details"
        pages.append(params)
        assert len(pages) <= 100, "pagination was not bounded"
        return {
            "items": [{"contentDetails": {"videoId": VIDEO}}],
            "nextPageToken": "repeat" if repeat else str(len(pages)),
        }

    monkeypatch.setattr(api, "_get", get)
    with pytest.raises(
        ValueError, match="^repeated_page_token$" if repeat else "^snapshot_page_limit$"
    ):
        api.snapshot(CHANNEL)
    assert len(pages) == (2 if repeat else 100)


@pytest.mark.parametrize("data", [{"items": []}, channel_response("UC" + "b" * 22)])
def test_snapshot_requires_exact_channel_identity(monkeypatch, data):
    from social.youtube import YouTube

    api = YouTube("fixture-key")
    calls = []
    monkeypatch.setattr(api, "_get", lambda *a, **k: calls.append(a) or data)
    with pytest.raises(ValueError, match="^channel_not_found$"):
        api.snapshot(CHANNEL)
    assert len(calls) == 1


def test_snapshot_validates_literal_channel_before_http(monkeypatch):
    from django.core.exceptions import ValidationError

    from social.youtube import YouTube

    api = YouTube("fixture-key")
    monkeypatch.setattr(api, "_get", lambda *a, **k: pytest.fail("malformed channel sent"))
    with pytest.raises(ValidationError):
        api.snapshot(" " + CHANNEL)


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"items": None},
        {"items": {}},
        {"items": [None]},
        {"items": [{"contentDetails": {}}]},
        {"items": [], "nextPageToken": ""},
        {"items": [], "nextPageToken": 7},
        {"items": [], "nextPageToken": None},
    ],
)
def test_snapshot_rejects_incomplete_or_malformed_pages(monkeypatch, response):
    from social.youtube import YouTube

    api = YouTube("fixture-key")
    monkeypatch.setattr(
        api,
        "_get",
        lambda resource, **k: channel_response() if resource == "channels" else response,
    )
    with pytest.raises(ValueError, match="^youtube_invalid_response$"):
        api.snapshot(CHANNEL)


@pytest.mark.parametrize(
    "change", ["missing_live", "empty_replay", "missing_title", "invalid_title", "missing_status"]
)
def test_details_fails_closed_on_incomplete_video_metadata(monkeypatch, change):
    from social.youtube import YouTube

    api = YouTube("fixture-key")
    item = video_item()
    if change == "missing_live":
        del item["snippet"]["liveBroadcastContent"]
    elif change == "empty_replay":
        item["liveStreamingDetails"] = {}
    elif change == "missing_title":
        del item["snippet"]["title"]
    elif change == "invalid_title":
        item["snippet"]["title"] = {"secret-provider-body": "do not stringify"}
    else:
        del item["status"]
    monkeypatch.setattr(api, "_get", lambda *a, **k: {"items": [item]})
    if change == "empty_replay":
        assert api.details([VIDEO], CHANNEL) == {}
    else:
        with pytest.raises(ValueError, match="^youtube_invalid_response$"):
            api.details([VIDEO], CHANNEL)


@pytest.mark.parametrize("response", [{}, {"items": None}, {"items": [None]}])
def test_details_sanitizes_malformed_video_lists(monkeypatch, response):
    from social.youtube import YouTube

    api = YouTube("fixture-key")
    monkeypatch.setattr(api, "_get", lambda *a, **k: response)
    with pytest.raises(ValueError, match="^youtube_invalid_response$"):
        api.details([VIDEO], CHANNEL)


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"items": None},
        {"items": [None]},
        {"items": [{}]},
        {"items": [{"id": CHANNEL}]},
        {"items": [{"id": CHANNEL, "contentDetails": {"relatedPlaylists": {"uploads": ""}}}]},
        {"items": [{"id": CHANNEL, "contentDetails": {"relatedPlaylists": {"uploads": []}}}]},
    ],
)
def test_snapshot_sanitizes_malformed_channel_metadata(monkeypatch, response):
    from social.youtube import YouTube

    api = YouTube("fixture-key")

    def get(resource, **params):
        assert resource == "channels", "malformed channel must not read a playlist"
        return response

    monkeypatch.setattr(api, "_get", get)
    with pytest.raises(ValueError, match="^youtube_invalid_response$"):
        api.snapshot(CHANNEL)


def test_details_rejects_unexpected_continuation_in_fifty_id_batch(monkeypatch):
    from social.youtube import YouTube

    api = YouTube("fixture-key")
    monkeypatch.setattr(
        api, "_get", lambda *a, **k: {"items": [video_item()], "nextPageToken": "more"}
    )
    with pytest.raises(ValueError, match="^youtube_invalid_response$"):
        api.details([VIDEO], CHANNEL)


def test_snapshot_rejects_malformed_ids_before_fetching_further_pages(monkeypatch):
    from social.youtube import YouTube

    api = YouTube("fixture-key")
    count = []

    def get(resource, **params):
        if resource == "channels":
            return channel_response()
        count.append(resource)
        assert len(count) == 1, "invalid video id allowed pagination to continue"
        return {"items": [{"contentDetails": {"videoId": "bad"}}], "nextPageToken": "more"}

    monkeypatch.setattr(api, "_get", get)
    with pytest.raises(ValueError, match="^youtube_invalid_response$"):
        api.snapshot(CHANNEL)
