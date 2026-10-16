import json
import traceback
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
import responses

GRAPH = "https://graph.facebook.com/v26.0/"
VIDEO_GRAPH = "https://graph-video.facebook.com/v26.0/"
WATCH = "https://www.facebook.com/watch/?v=456"


@responses.activate
def test_link_fields_explicit_and_readback_exact_target():
    from social.facebook import Facebook

    api = Facebook("123", "fixture-token")
    url = "https://www.youtube.com/watch?v=" + "a" * 11
    responses.post(GRAPH + "123/feed", json={"id": "123_456"})
    responses.get(
        GRAPH + "123_456",
        json={
            "id": "123_456",
            "from": {"id": "123"},
            "permalink_url": "https://www.facebook.com/123_456",
        },
    )
    assert api.publish_link("ชื่อคลิป", url) == "123_456"
    assert api.verify("123_456", "link") == "https://www.facebook.com/123_456"
    request = responses.calls[0].request
    assert json.loads(request.body) == {"message": "ชื่อคลิป", "link": url, "published": True}
    assert request.headers["Authorization"] == "Bearer fixture-token"
    assert "fixture-token" not in request.url
    assert parse_qs(urlsplit(responses.calls[1].request.url).query) == {
        "fields": ["id,from,permalink_url"]
    }


@pytest.mark.parametrize(
    "data",
    [
        {"id": "999", "from": {"id": "123"}},
        {"id": "123_456", "from": {"id": "999"}},
        {"id": "123_456"},
        {"id": "123_456", "from": None},
        {"id": "123_456", "from": {"id": 123}},
    ],
)
@responses.activate
def test_verify_rejects_non_exact_object_or_owner(data):
    from social.facebook import Facebook

    responses.get(GRAPH + "123_456", json=data)
    with pytest.raises(ValueError, match="^remote_owner_mismatch$"):
        Facebook("123", "fixture-token").verify("123_456", "photo")


@pytest.mark.parametrize(
    "source,want", [("https://cdn.example/signed-secret", WATCH), ("", None), (None, None)]
)
@responses.activate
def test_video_readback_checks_source_without_returning_signed_url(source, want):
    from social.facebook import Facebook

    responses.get(GRAPH + "456", json={"id": "456", "from": {"id": "123"}, "source": source})
    assert Facebook("123", "fixture-token").verify("456", "video") == want
    assert parse_qs(urlsplit(responses.calls[0].request.url).query) == {
        "fields": ["id,from,source"]
    }


@pytest.mark.parametrize(
    "remote_id,kind",
    [
        ("123/456", "link"),
        ("_", "link"),
        ("123__456", "photo"),
        ("123_", "photo"),
        (" 456", "video"),
        (456, "video"),
        ("456", "unknown"),
        ("123_456", "video"),
    ],
)
def test_invalid_remote_target_never_calls_http(remote_id, kind, monkeypatch):
    from social.facebook import Facebook

    api = Facebook("123", "fixture-token")
    monkeypatch.setattr(api.session, "get", lambda *a, **k: pytest.fail("invalid target sent"))
    with pytest.raises(ValueError):
        api.verify(remote_id, kind)


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize(
    "failure,code",
    [
        (403, "facebook_http_403"),
        (429, "facebook_http_429"),
        (500, "facebook_http_500"),
        ("transport", "facebook_request_failed"),
        ("json", "facebook_invalid_response"),
        ("error", "facebook_api_error"),
        ("list", "facebook_invalid_response"),
    ],
)
@responses.activate
def test_provider_failures_are_sanitized_and_never_retried(method, failure, code):
    from social.facebook import Facebook

    api = Facebook("123", "fixture-token")
    register = responses.get if method == "get" else responses.post
    endpoint = GRAPH + ("123_456" if method == "get" else "123/feed")
    if isinstance(failure, int):
        register(endpoint, status=failure, body="secret-provider-body fixture-token")
    elif failure == "transport":
        register(endpoint, body=requests.Timeout("fixture-token secret-provider-body"))
    elif failure == "json":
        register(endpoint, body="fixture-token secret-provider-body")
    else:
        register(endpoint, json={"error": "secret-provider-body"} if failure == "error" else [])
    with pytest.raises(RuntimeError, match=f"^{code}$") as caught:
        if method == "get":
            api.verify("123_456", "photo")
        else:
            api.publish_link("clip", "https://www.youtube.com/watch?v=" + "a" * 11)
    output = "".join(traceback.format_exception(caught.value))
    assert "fixture-token" not in output and "secret-provider-body" not in output
    assert len(responses.calls) == 1


@pytest.mark.parametrize("method,status", [("post", 307), ("get", 302)])
@responses.activate
def test_credential_bearing_requests_never_follow_redirects(method, status, monkeypatch):
    from social.facebook import Facebook

    api = Facebook("123", "fixture-token")
    endpoint = GRAPH + ("123_456" if method == "get" else "123/feed")
    register = responses.get if method == "get" else responses.post
    register(endpoint, status=status, headers={"Location": GRAPH + "another"})
    register(GRAPH + "another", json={"id": "123_456", "from": {"id": "123"}})
    real = getattr(api.session, method)
    options = []

    def request(*args, **kwargs):
        options.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(api.session, method, request)
    with pytest.raises(RuntimeError, match=f"^facebook_http_{status}$"):
        if method == "get":
            api.verify("123_456", "photo")
        else:
            api.publish_link("clip", "https://www.youtube.com/watch?v=" + "a" * 11)
    assert len(responses.calls) == 1
    assert options[0]["timeout"] == (10, 60)
    assert options[0]["allow_redirects"] is False
    assert api.session.get_adapter(GRAPH).max_retries.total == 0


@pytest.mark.parametrize(
    "page,token,version",
    [
        (" 123", "fixture-token", "v26.0"),
        ("123/456", "fixture-token", "v26.0"),
        ("123", "", "v26.0"),
        ("123", "a\nb", "v26.0"),
        ("123", None, "v26.0"),
        ("123", "fixture-token", "v25.0"),
    ],
)
def test_invalid_facebook_configuration_rejected(page, token, version):
    from django.core.exceptions import ValidationError

    from social.facebook import Facebook

    with pytest.raises((ValueError, ValidationError)):
        Facebook(page, token, version)


@pytest.mark.parametrize("failure", [False, True])
def test_video_upload_streams_file_and_closes_it_even_on_transport_failure(
    tmp_path, monkeypatch, failure
):
    from types import SimpleNamespace

    from requests_toolbelt.multipart.encoder import MultipartEncoder

    from social.facebook import Facebook

    path = tmp_path / "private-original.mp4"
    path.write_bytes(b"offline-fixture-not-real-media")
    api = Facebook("123", "fixture-token")
    sources = []

    def post(url, **kwargs):
        assert url == VIDEO_GRAPH + "123/videos"
        body = kwargs["data"]
        assert isinstance(body, MultipartEncoder)
        assert "files" not in kwargs
        assert body.fields["title"] == "ชื่อคลิป"
        assert body.fields["description"] == "description"
        assert {key: body.fields[key] for key in ("published", "secret", "no_story")} == {
            "published": "true",
            "secret": "false",
            "no_story": "false",
        }
        # Page lacks Video Copyright API onboarding; this field makes Graph reject uploads.
        assert "reference_only" not in body.fields
        filename, source, content_type = body.fields["source"]
        assert filename == "original.mp4" and content_type == "video/mp4"
        assert hasattr(source, "read") and not isinstance(source, bytes)
        assert not source.closed and source.tell() == 0
        sources.append(source)
        assert kwargs["headers"] == {"Content-Type": body.content_type}
        assert kwargs["timeout"] == (10, 600)
        assert kwargs["allow_redirects"] is False
        if failure:
            raise requests.Timeout("secret provider details")
        return SimpleNamespace(status_code=200, json=lambda: {"id": "456"})

    monkeypatch.setattr(api.session, "post", post)
    if failure:
        with pytest.raises(RuntimeError, match="^facebook_request_failed$"):
            api.publish_video(path, "ชื่อคลิป", "description")
    else:
        assert api.publish_video(path, "ชื่อคลิป", "description") == "456"
    assert len(sources) == 1 and sources[0].closed


@responses.activate
def test_photo_returns_page_post_id_not_photo_id_with_exact_payload():
    from social.facebook import Facebook

    image = "https://i.ytimg.com/vi/aaaaaaaaaaa/hqdefault.jpg"
    caption = "ชื่อคลิป\ntag: #katy404 #vtuberth #short #วีทูปเบอร์ไทย"
    responses.post(GRAPH + "123/photos", json={"id": "456", "post_id": "123_789"})
    assert Facebook("123", "fixture-token").publish_photo(caption, image) == "123_789"
    assert json.loads(responses.calls[0].request.body) == {
        "message": caption,
        "url": image,
        "published": True,
    }
    assert len(responses.calls) == 1


@pytest.mark.parametrize(
    "image", ["https://evil.example/a.jpg", "http://i.ytimg.com/a.jpg", "", None]
)
def test_photo_rejects_untrusted_thumbnail_before_post(image, monkeypatch):
    from social.facebook import Facebook

    api = Facebook("123", "fixture-token")
    monkeypatch.setattr(
        api.session, "post", lambda *a, **k: pytest.fail("untrusted thumbnail sent")
    )
    with pytest.raises(ValueError, match="^invalid_thumbnail_url$"):
        api.publish_photo("clip", image)


@pytest.mark.parametrize(
    "kind,result",
    [
        ("link", {}),
        ("link", {"id": None}),
        ("link", {"id": 456}),
        ("link", {"id": "fixture-token"}),
        ("link", {"id": "999_456"}),
        ("photo", {"id": "456"}),
        ("photo", {"post_id": "456"}),
        ("photo", {"post_id": "999_456"}),
        ("photo", {"post_id": "123_"}),
        ("video", {"id": "123_456"}),
        ("video", {"id": "secret-provider-body"}),
    ],
)
@responses.activate
def test_publish_rejects_missing_malformed_or_wrong_page_remote_ids(kind, result, tmp_path):
    from social.facebook import Facebook

    api = Facebook("123", "fixture-token")
    endpoint = (
        VIDEO_GRAPH + "123/videos"
        if kind == "video"
        else GRAPH + "123/" + ("feed" if kind == "link" else "photos")
    )
    responses.post(endpoint, json=result)
    with pytest.raises(ValueError, match="^invalid_remote_id$") as caught:
        if kind == "link":
            api.publish_link("clip", "https://www.youtube.com/watch?v=" + "a" * 11)
        elif kind == "photo":
            api.publish_photo("clip", "https://i.ytimg.com/vi/aaaaaaaaaaa/hqdefault.jpg")
        else:
            path = tmp_path / "original.mp4"
            path.write_bytes(b"fixture")
            api.publish_video(path, "clip", "description")
    assert "fixture-token" not in str(caught.value)
    assert len(responses.calls) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/post",
        "javascript:alert(1)",
        "http://www.facebook.com/post",
        "https://user:secret@www.facebook.com/post",
        "https://www.facebook.com.evil.example/post",
        {"body": "secret"},
        "https://www.facebook.com:444/post",
        "https://www.facebook.com/\npost",
    ],
)
@responses.activate
def test_readback_rejects_untrusted_or_malformed_permalink(url):
    from social.facebook import Facebook

    responses.get(
        GRAPH + "123_456", json={"id": "123_456", "from": {"id": "123"}, "permalink_url": url}
    )
    with pytest.raises(ValueError, match="^facebook_invalid_response$"):
        Facebook("123", "fixture-token").verify("123_456", "photo")


@pytest.mark.parametrize("source", [True, 1, {"signed": "secret"}, ["secret"]])
@responses.activate
def test_video_readback_requires_string_source_not_truthy_json(source):
    from social.facebook import Facebook

    responses.get(GRAPH + "456", json={"id": "456", "from": {"id": "123"}, "source": source})
    with pytest.raises(ValueError, match="^facebook_invalid_response$"):
        Facebook("123", "fixture-token").verify("456", "video")
