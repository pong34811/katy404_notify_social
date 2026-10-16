import pytest


@pytest.mark.parametrize(
    "url",
    [
        "https://i.ytimg.com/vi/aaaaaaaaaaa/hqdefault.jpg",
        "https://i9.ytimg.com/vi/aaaaaaaaaaa/default.jpg",
        "https://i.ytimg.com:443/vi/aaaaaaaaaaa/high.jpg?existing=1",
    ],
)
def test_thumbnail_url_accepts_only_trusted_https_hosts(url):
    from social.notifications import valid_thumbnail_url

    assert valid_thumbnail_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://i.ytimg.com/a.jpg",
        "//i.ytimg.com/a.jpg",
        "https://evil.example/a.jpg",
        "https://i.ytimg.com.evil.example/a.jpg",
        "https://i.ytimg.com@evil.example/a.jpg",
        "https://evil.example@i.ytimg.com/a.jpg",
        "https://:password@i.ytimg.com/a.jpg",
        "https://@i.ytimg.com/a.jpg",
        "https://i.ytimg.com:8443/a.jpg",
        "https://i.ytimg.com:invalid/a.jpg",
        "https://i.ytimg.com:99999/a.jpg",
        "https://i.ytimg.com:/a.jpg",
        "https://i.ytimg.com\\evil.example/a.jpg",
        "https://[broken/a.jpg",
        " https://i.ytimg.com/a.jpg",
        "https://i.ytimg.com/a\n.jpg",
        "https://i.ytimg.com/a\t.jpg",
        "https://i.ytimg.com/a b.jpg",
        "https://i.ytimg.com/a\x00.jpg",
        "",
        None,
        42,
        b"https://i.ytimg.com/a.jpg",
    ],
)
def test_thumbnail_url_rejects_untrusted_or_ambiguous_urls(url):
    from social.notifications import valid_thumbnail_url

    assert valid_thumbnail_url(url) is False


@pytest.mark.parametrize("best", ["maxres", "standard", "high", "medium", "default"])
def test_choose_thumbnail_uses_existing_api_urls_in_priority_order(best):
    from social.notifications import choose_thumbnail

    keys = ["maxres", "standard", "high", "medium", "default"]
    thumbnails = {
        key: {"url": f"https://i.ytimg.com/vi/aaaaaaaaaaa/{key}.jpg"}
        for key in keys[keys.index(best) :]
    }
    assert choose_thumbnail(thumbnails) == thumbnails[best]["url"]


def test_choose_thumbnail_skips_invalid_or_missing_candidates():
    from social.notifications import choose_thumbnail

    high = "https://i9.ytimg.com/vi/aaaaaaaaaaa/hqdefault.jpg?returned=1"
    assert (
        choose_thumbnail(
            {
                "maxres": {"url": "https://evil.example/picture.jpg"},
                "standard": {},
                "high": {"url": high},
            }
        )
        == high
    )
    assert choose_thumbnail({}) == ""
    assert choose_thumbnail({"maxres": {"url": "http://i.ytimg.com/a.jpg"}}) == ""


@pytest.mark.parametrize("thumbnails", [None, [], "invalid", {"maxres": None}, {"high": []}])
def test_choose_thumbnail_treats_malformed_metadata_as_missing(thumbnails):
    from social.notifications import choose_thumbnail

    assert choose_thumbnail(thumbnails) == ""


@pytest.mark.parametrize("title", ["ชื่อคลิปทดสอบ", "  literal title  ", "", "title\nsecond line"])
def test_landscape_caption_preserves_title_and_exact_tags(title):
    from social.notifications import landscape_message

    assert landscape_message(title) == f"{title}\ntag: #katy404 #vtuberth #short #วีทูปเบอร์ไทย"
