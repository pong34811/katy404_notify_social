"""Explicit Page publishing and exact-object readback (not a visibility guarantee)."""

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests
from requests_toolbelt.multipart.encoder import MultipartEncoder

from .notifications import valid_thumbnail_url
from .validators import page_id_validator


class Facebook:
    def __init__(self, page_id: str, token: str, version: str = "v26.0"):
        page_id_validator(page_id)
        if (
            not isinstance(token, str)
            or not token
            or any(c.isspace() for c in token)
            or version != "v26.0"
        ):
            raise ValueError("facebook_configuration")
        self.page_id, self.version = page_id, version
        self.session = requests.Session()
        self.session.mount("https://", requests.adapters.HTTPAdapter(max_retries=0))
        self.session.headers["Authorization"] = f"Bearer {token}"

    def _json(self, response) -> dict:
        try:
            data = response.json()
        except ValueError:
            data = None
        error = data.get("error") if isinstance(data, dict) else None
        if not 200 <= response.status_code < 300:
            raise RuntimeError(self._api_error(response.status_code, error))
        if not isinstance(data, dict):
            raise RuntimeError("facebook_invalid_response")  # noqa: TRY004 - provider schema failure
        if "error" in data:
            raise RuntimeError(self._api_error(None, error))
        return data

    @staticmethod
    def _api_error(status_code: int | None, error) -> str:
        code = f"facebook_http_{status_code}" if status_code is not None else "facebook_api_error"
        if isinstance(error, dict):
            api_code = error.get("code")
            subcode = error.get("error_subcode")
            if isinstance(api_code, int) and not isinstance(api_code, bool) and api_code >= 0:
                code += f"_code_{api_code}"
            if isinstance(subcode, int) and not isinstance(subcode, bool) and subcode >= 0:
                code += f"_subcode_{subcode}"
        return code

    def _request(self, method: str, url: str, **kwargs) -> dict:
        try:
            response = getattr(self.session, method)(url, allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise RuntimeError("facebook_request_failed") from None
        return self._json(response)

    def _published_id(self, value, kind: str) -> str:
        pattern = r"[0-9]+" if kind == "video" else re.escape(self.page_id) + r"_[0-9]+"
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            raise ValueError("invalid_remote_id")
        return value

    def publish_link(self, message: str, url: str) -> str:
        result = self._request(
            "post",
            f"https://graph.facebook.com/{self.version}/{self.page_id}/feed",
            json={"message": message, "link": url, "published": True},
            timeout=(10, 60),
        )
        return self._published_id(result.get("id"), "link")

    def publish_photo(self, message: str, thumbnail_url: str) -> str:
        if not valid_thumbnail_url(thumbnail_url):
            raise ValueError("invalid_thumbnail_url")
        result = self._request(
            "post",
            f"https://graph.facebook.com/{self.version}/{self.page_id}/photos",
            json={"message": message, "url": thumbnail_url, "published": True},
            timeout=(10, 60),
        )
        # The photo object's id is not the published Page post's id.
        return self._published_id(result.get("post_id"), "photo")

    def publish_video(
        self, path: Path, title: str, description: str, scheduled_at: datetime | None = None
    ) -> str:
        fields = {
            "title": title,
            "description": description,
            "published": "true",
            "secret": "false",
            "no_story": "false",
        }
        if scheduled_at is not None:
            if not isinstance(scheduled_at, datetime) or scheduled_at.utcoffset() is None:
                raise ValueError("invalid_scheduled_at")
            fields["published"] = "false"
            fields["scheduled_publish_time"] = str(int(scheduled_at.timestamp()))
        with Path(path).open("rb") as source:
            body = MultipartEncoder(
                fields={
                    "source": ("original.mp4", source, "video/mp4"),
                    **fields,
                }
            )
            result = self._request(
                "post",
                f"https://graph-video.facebook.com/{self.version}/{self.page_id}/videos",
                data=body,
                headers={"Content-Type": body.content_type},
                timeout=(10, 600),
            )
        return self._published_id(result.get("id"), "video")

    def verify_scheduled_video(self, remote_id: str, scheduled_at: datetime) -> bool:
        self._published_id(remote_id, "video")
        if not isinstance(scheduled_at, datetime) or scheduled_at.utcoffset() is None:
            raise ValueError("invalid_scheduled_at")
        data = self._request(
            "get",
            f"https://graph.facebook.com/{self.version}/{remote_id}",
            params={
                "fields": "id,from,scheduled_publish_time",
            },
            timeout=(10, 60),
        )
        owner = data.get("from")
        if (
            data.get("id") != remote_id
            or not isinstance(owner, dict)
            or owner.get("id") != self.page_id
        ):
            raise ValueError("remote_owner_mismatch")
        published_at = data.get("scheduled_publish_time")
        try:
            actual = (
                datetime.fromtimestamp(float(published_at), scheduled_at.tzinfo)
                if isinstance(published_at, (int, float)) and not isinstance(published_at, bool)
                else datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
            )
            matches_time = int(actual.timestamp()) == int(scheduled_at.timestamp())
        except (TypeError, ValueError, OverflowError, OSError):
            return False
        return matches_time

    def verify(self, remote_id: str, kind: str) -> str | None:
        if kind not in {"video", "photo", "link"}:
            raise ValueError("invalid_remote_kind")
        pattern = r"[0-9]+" if kind == "video" else r"[0-9]+(?:_[0-9]+)?"
        if not isinstance(remote_id, str) or not re.fullmatch(pattern, remote_id):
            raise ValueError("invalid_remote_id")
        fields = "id,from,source" if kind == "video" else "id,from,permalink_url"
        data = self._request(
            "get",
            f"https://graph.facebook.com/{self.version}/{remote_id}",
            params={"fields": fields},
            timeout=(10, 60),
        )
        owner = data.get("from")
        if (
            data.get("id") != remote_id
            or not isinstance(owner, dict)
            or owner.get("id") != self.page_id
        ):
            raise ValueError("remote_owner_mismatch")
        if kind == "video":
            source = data.get("source")
            if source is not None and not isinstance(source, str):
                raise ValueError("facebook_invalid_response")
            # Never return or persist the provider's signed video-file URL.
            return f"https://www.facebook.com/watch/?v={remote_id}" if source else None
        url = data.get("permalink_url")
        if url is None or url == "":
            return None
        if (
            not isinstance(url, str)
            or "\\" in url
            or any(ord(c) <= 32 or ord(c) == 127 for c in url)
        ):
            raise ValueError("facebook_invalid_response")
        try:
            parsed = urlsplit(url)
            valid = (
                parsed.scheme == "https"
                and parsed.hostname in {"facebook.com", "www.facebook.com"}
                and parsed.username is None
                and parsed.password is None
                and parsed.port in {None, 443}
            )
        except ValueError:
            raise ValueError("facebook_invalid_response") from None
        if not valid:
            raise ValueError("facebook_invalid_response")
        return url
