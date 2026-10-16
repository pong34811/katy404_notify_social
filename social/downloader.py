"""Optional yt-dlp wrapper. Opt-in (YT_DOWNLOAD=1), no cookies, one video ID at a time."""

import json
import re
import subprocess
import sys
from pathlib import Path

ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
FORMAT = "bv*[vcodec^=avc1][ext=mp4]+ba[ext=m4a]/b[vcodec^=avc1][ext=mp4]/b[ext=mp4]"
MAX_FILESIZE = "250M"


class DownloadError(Exception):
    """Public-safe download failure; never carries URLs, cookies or tool output."""


def _url(video_id):
    if not ID_RE.fullmatch(video_id or ""):
        raise DownloadError("invalid_video_id")
    return f"https://www.youtube.com/watch?v={video_id}"


def _run(args, timeout):
    try:
        result = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-warnings", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise DownloadError("ytdlp_failed") from None
    if result.returncode != 0:
        raise DownloadError("ytdlp_failed")
    return result


def info(video_id):
    """Return (width, height, duration) without downloading the media."""
    result = _run(["--dump-json", "--skip-download", "-f", FORMAT, _url(video_id)], 120)
    try:
        data = json.loads(result.stdout)
        return float(data["width"]), float(data["height"]), float(data["duration"])
    except (ValueError, KeyError, TypeError):
        raise DownloadError("ytdlp_bad_metadata") from None


def download(video_id, dest_dir):
    url = _url(video_id)
    dest_dir = Path(dest_dir)
    _run(
        [
            "-f",
            FORMAT,
            "--merge-output-format",
            "mp4",
            "--max-filesize",
            MAX_FILESIZE,
            "-o",
            str(dest_dir / f"{video_id}.%(ext)s"),
            url,
        ],
        1200,
    )
    path = dest_dir / f"{video_id}.mp4"
    if not path.is_file():
        raise DownloadError("ytdlp_no_output")
    return path
