"""Inspect private originals and apply the editorial delivery rule."""

import json
import math
import os
import subprocess
from fractions import Fraction
from pathlib import Path

MAX_BYTES = 250 * 1024 * 1024


class _MediaError(ValueError):
    """A deliberately public-safe media validation code."""


def probe(path: Path) -> tuple[float, float, float]:
    try:
        path = Path(path)
        if path.suffix.lower() != ".mp4" or not 0 < path.stat().st_size <= MAX_BYTES:
            raise _MediaError("invalid_file_size_or_extension")
        result = subprocess.run(
            [
                os.getenv("FFPROBE_BIN", "ffprobe"),
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path.resolve()),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
            shell=False,
        )
        data = json.loads(result.stdout)
        streams = data["streams"]
        videos = [
            s
            for s in streams
            if s.get("codec_type") == "video"
            and not s.get("disposition", {}).get("attached_pic", 0)
        ]
        if len(videos) != 1:
            raise _MediaError("invalid_video_stream_count")
        stream = videos[0]
        if stream.get("codec_name") != "h264":
            raise _MediaError("unsupported_video_codec")
        if any(s.get("codec_name") != "aac" for s in streams if s.get("codec_type") == "audio"):
            raise _MediaError("unsupported_audio_codec")
        if "mp4" not in data["format"].get("format_name", "").split(","):
            raise _MediaError("unsupported_container")
        sar = Fraction(stream.get("sample_aspect_ratio", "1:1").replace(":", "/"))
        width, height = float(stream["width"]) * float(sar), float(stream["height"])
        duration = float(data["format"]["duration"])
        if sar <= 0 or not all(math.isfinite(x) and x > 0 for x in (width, height, duration)):
            raise _MediaError("invalid_geometry_or_duration")
        if duration > 1800:
            raise _MediaError("duration_limit")
        rotation_value = next(
            (s["rotation"] for s in stream.get("side_data_list", []) if "rotation" in s), None
        )
        if rotation_value is None:
            rotation_value = stream.get("tags", {}).get("rotate", 0)
        rotation = float(rotation_value)
        if not math.isfinite(rotation) or rotation % 90:
            raise _MediaError("unsupported_rotation")
        if rotation % 180:
            width, height = height, width
        return width, height, duration
    except _MediaError as exc:
        raise ValueError(str(exc)) from None
    except (
        KeyError,
        TypeError,
        ValueError,
        ZeroDivisionError,
        OverflowError,
        AttributeError,
        subprocess.SubprocessError,
        OSError,
    ):
        raise ValueError("invalid_media") from None


def _valid_geometry(width: float, height: float, duration: float) -> bool:
    return all(math.isfinite(x) and x > 0 for x in (width, height, duration)) and duration <= 1800


def eligible(width: float, height: float, duration: float) -> bool:
    return _valid_geometry(width, height, duration) and (
        height > width or (height == width and duration <= 180)
    )


def route_for_geometry(width: float, height: float, duration: float) -> str:
    if not _valid_geometry(width, height, duration):
        return "skip"
    if width > height:
        return "photo"
    return "video" if eligible(width, height, duration) else "skip"
