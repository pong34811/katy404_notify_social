"""Read-only public YouTube metadata; never downloads audiovisual files."""

import requests
from django.core.exceptions import ValidationError

from .notifications import choose_thumbnail
from .validators import channel_id_validator, video_id_validator


def _items(data: dict) -> list[dict]:
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError("youtube_invalid_response")
    return items


class YouTube:
    def __init__(self, key: str):
        if not isinstance(key, str) or not key or any(c.isspace() for c in key):
            raise ValueError("youtube_key_missing_or_invalid")
        self.key = key
        self.session = requests.Session()
        self.session.mount("https://", requests.adapters.HTTPAdapter(max_retries=0))

    def _get(self, resource: str, **params) -> dict:
        if resource not in {"channels", "playlistItems", "videos"}:
            raise ValueError("youtube_resource")
        try:
            response = self.session.get(
                f"https://www.googleapis.com/youtube/v3/{resource}",
                params={**params, "key": self.key},
                timeout=(10, 60),
                allow_redirects=False,
            )
        except requests.RequestException:
            raise RuntimeError("youtube_request_failed") from None
        if response.status_code != 200:
            raise RuntimeError(f"youtube_http_{response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise RuntimeError("youtube_invalid_response") from None
        if not isinstance(data, dict):
            raise RuntimeError("youtube_invalid_response")  # noqa: TRY004 - provider schema failure
        if "error" in data:
            raise RuntimeError("youtube_api_error")
        return data

    def details(self, ids: list[str], channel_id: str) -> dict[str, dict]:
        channel_id_validator(channel_id)
        for vid in ids:
            video_id_validator(vid)
        ids = list(dict.fromkeys(ids))
        found = {}
        for start in range(0, len(ids), 50):
            batch = ids[start : start + 50]
            data = self._get(
                "videos",
                part="snippet,status,contentDetails,liveStreamingDetails",
                id=",".join(batch),
                maxResults=50,
            )
            if "nextPageToken" in data:
                raise ValueError("youtube_invalid_response")
            seen = set()
            for item in _items(data):
                try:
                    vid, snippet = item["id"], item["snippet"]
                    owner = snippet["channelId"]
                    privacy, live = item["status"]["privacyStatus"], snippet["liveBroadcastContent"]
                except (KeyError, TypeError):
                    raise ValueError("youtube_invalid_response") from None
                if vid not in batch or owner != channel_id:
                    raise ValueError("source_channel_mismatch")
                if vid in seen:
                    raise ValueError("duplicate_video_item")
                seen.add(vid)
                if privacy != "public":
                    continue
                if live != "none":
                    continue
                live_details = item.get("liveStreamingDetails")
                if live_details is not None and not (
                    isinstance(live_details, dict)
                    and isinstance(live_details.get("actualEndTime"), str)
                    and live_details["actualEndTime"]
                ):
                    # Exclude active/upcoming/unfinished broadcasts, but include
                    # public completed live replays from the uploads playlist.
                    continue
                if not isinstance(snippet.get("title"), str):
                    raise ValueError("youtube_invalid_response")  # noqa: TRY004 - provider schema failure
                found[vid] = {
                    "title": snippet["title"],
                    "thumbnail_url": choose_thumbnail(snippet.get("thumbnails", {})),
                }
        return found

    def snapshot(self, channel_id: str) -> dict[str, dict]:
        channel_id_validator(channel_id)
        data = self._get("channels", part="contentDetails", id=channel_id)
        items = _items(data)
        if len(items) != 1:
            raise ValueError("channel_not_found")
        try:
            owner = items[0]["id"]
            playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        except (KeyError, TypeError):
            raise ValueError("youtube_invalid_response") from None
        if owner != channel_id:
            raise ValueError("channel_not_found")
        if not isinstance(playlist, str) or not playlist:
            raise ValueError("youtube_invalid_response")
        ids, tokens, token = [], set(), None
        for _ in range(100):
            params = {"part": "contentDetails", "playlistId": playlist, "maxResults": 50}
            if token:
                params["pageToken"] = token
            page = self._get("playlistItems", **params)
            for item in _items(page):
                try:
                    vid = item["contentDetails"]["videoId"]
                except (KeyError, TypeError):
                    raise ValueError("youtube_invalid_response") from None
                try:
                    video_id_validator(vid)
                except ValidationError:
                    raise ValueError("youtube_invalid_response") from None
                ids.append(vid)
            if "nextPageToken" not in page:
                return self.details(list(dict.fromkeys(ids)), channel_id)
            token = page["nextPageToken"]
            if not isinstance(token, str) or not token:
                raise ValueError("youtube_invalid_response")
            if token in tokens:
                raise ValueError("repeated_page_token")
            tokens.add(token)
        raise ValueError("snapshot_page_limit")
