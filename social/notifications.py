"""Exact landscape captions and API-provided thumbnail selection."""

from urllib.parse import urlsplit

LANDSCAPE_TAG_LINE = "tag: #katy404 #vtuberth #short #วีทูปเบอร์ไทย"


def valid_thumbnail_url(url: str) -> bool:
    if not isinstance(url, str) or not url or any(ord(c) <= 32 or ord(c) == 127 for c in url):
        return False
    if "\\" in url:
        return False
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname in {"i.ytimg.com", "i9.ytimg.com"}
            and parsed.username is None
            and parsed.password is None
            and parsed.port in {None, 443}
            and not parsed.netloc.endswith(":")
        )
    except (ValueError, TypeError):
        return False


def choose_thumbnail(thumbnails: dict) -> str:
    if not isinstance(thumbnails, dict):
        return ""
    for key in ("maxres", "standard", "high", "medium", "default"):
        candidate = thumbnails.get(key)
        if not isinstance(candidate, dict):
            continue
        url = candidate.get("url", "")
        if valid_thumbnail_url(url):
            return url
    return ""


def landscape_message(title: str) -> str:
    return f"{title}\n{LANDSCAPE_TAG_LINE}"
