import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def original(tmp_path):
    path = tmp_path / "private-original.mp4"
    path.write_bytes(b"offline-ffprobe-fixture")
    return path


@pytest.fixture
def metadata(monkeypatch):
    import subprocess

    payload = {
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "30"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "sample_aspect_ratio": "1:1",
            }
        ],
    }
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(stdout=json.dumps(payload), returncode=0),
    )
    return payload


@pytest.mark.parametrize(
    "sar,rotation,want",
    [
        ("1:1", 90, (1080.0, 1920.0, 30.0)),
        ("1:1", 270, (1080.0, 1920.0, 30.0)),
        ("1:1", -90, (1080.0, 1920.0, 30.0)),
        ("1:1", 180, (1920.0, 1080.0, 30.0)),
        ("2:1", 0, (3840.0, 1080.0, 30.0)),
        ("2:1", 90, (1080.0, 3840.0, 30.0)),
    ],
)
def test_probe_uses_sample_aspect_ratio_before_rotation(original, metadata, sar, rotation, want):
    from social.media import probe

    metadata["streams"][0].update(
        sample_aspect_ratio=sar,
        side_data_list=[{"rotation": rotation}],
    )
    assert probe(original) == want


def test_probe_falls_back_to_legacy_rotation_tag(original, metadata):
    from social.media import probe

    metadata["streams"][0]["tags"] = {"rotate": "270"}
    assert probe(original) == (1080.0, 1920.0, 30.0)


def test_probe_prefers_side_data_over_legacy_tag(original, metadata):
    from social.media import probe

    metadata["streams"][0].update(side_data_list=[{"rotation": 90}], tags={"rotate": "invalid"})
    assert probe(original) == (1080.0, 1920.0, 30.0)


@pytest.mark.parametrize(
    "change,code",
    [
        ({"codec_name": "hevc"}, "unsupported_video_codec"),
        ({"width": 0}, "invalid_geometry_or_duration"),
        ({"width": -1920}, "invalid_geometry_or_duration"),
        ({"width": "NaN"}, "invalid_geometry_or_duration"),
        ({"height": "Infinity"}, "invalid_geometry_or_duration"),
        ({"sample_aspect_ratio": "0:1"}, "invalid_geometry_or_duration"),
        ({"sample_aspect_ratio": "-1:1"}, "invalid_geometry_or_duration"),
        ({"sample_aspect_ratio": "N/A"}, "invalid_media"),
        ({"sample_aspect_ratio": "1:0"}, "invalid_media"),
        ({"sample_aspect_ratio": "private-secret"}, "invalid_media"),
        ({"side_data_list": [{"rotation": 90.5}]}, "unsupported_rotation"),
        ({"side_data_list": [{"rotation": "NaN"}]}, "unsupported_rotation"),
        ({"side_data_list": [{"rotation": "Infinity"}]}, "unsupported_rotation"),
        ({"side_data_list": [{"rotation": "private-secret"}]}, "invalid_media"),
    ],
)
def test_probe_rejects_unsupported_video_metadata(original, metadata, change, code):
    from social.media import probe

    metadata["streams"][0].update(change)
    with pytest.raises(ValueError, match=f"^{code}$") as error:
        probe(original)
    assert error.value.__cause__ is None


@pytest.mark.parametrize(
    "duration,code",
    [
        ("NaN", "invalid_geometry_or_duration"),
        ("Infinity", "invalid_geometry_or_duration"),
        ("-1", "invalid_geometry_or_duration"),
        ("0", "invalid_geometry_or_duration"),
        ("1800.01", "duration_limit"),
        ("private-secret", "invalid_media"),
    ],
)
def test_probe_rejects_invalid_duration(original, metadata, duration, code):
    from social.media import probe

    metadata["format"]["duration"] = duration
    with pytest.raises(ValueError, match=f"^{code}$"):
        probe(original)


def test_probe_rejects_missing_dimensions(original, metadata):
    from social.media import probe

    del metadata["streams"][0]["width"]
    with pytest.raises(ValueError, match="^invalid_media$"):
        probe(original)


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("streams", [], "invalid_video_stream_count"),
        ("streams", [{"codec_type": "audio", "codec_name": "aac"}], "invalid_video_stream_count"),
        ("format", {"format_name": "matroska", "duration": "30"}, "unsupported_container"),
    ],
)
def test_probe_rejects_invalid_container_or_streams(original, metadata, field, value, code):
    from social.media import probe

    metadata[field] = value
    with pytest.raises(ValueError, match=f"^{code}$"):
        probe(original)


def test_probe_rejects_multiple_video_streams(original, metadata):
    from social.media import probe

    metadata["streams"].append(dict(metadata["streams"][0]))
    with pytest.raises(ValueError, match="^invalid_video_stream_count$"):
        probe(original)


@pytest.mark.parametrize("codec,want_error", [("aac", False), ("mp3", True), (None, True)])
def test_probe_allows_only_aac_audio(original, metadata, codec, want_error):
    from social.media import probe

    metadata["streams"].append({"codec_type": "audio", "codec_name": codec})
    if want_error:
        with pytest.raises(ValueError, match="^unsupported_audio_codec$"):
            probe(original)
    else:
        assert probe(original) == (1920.0, 1080.0, 30.0)


def test_probe_ignores_attached_cover_art(original, metadata):
    from social.media import probe

    metadata["streams"].insert(
        0, {"codec_type": "video", "codec_name": "mjpeg", "disposition": {"attached_pic": 1}}
    )
    assert probe(original) == (1920.0, 1080.0, 30.0)


@pytest.mark.parametrize(
    "size,suffix,valid",
    [
        (0, ".mp4", False),
        (1, ".avi", False),
        (250 * 1024 * 1024 + 1, ".mp4", False),
        (250 * 1024 * 1024, ".MP4", True),
    ],
)
def test_probe_enforces_file_size_and_extension(
    original, metadata, monkeypatch, size, suffix, valid
):
    from pathlib import Path

    from social.media import MAX_BYTES, probe

    assert MAX_BYTES == 250 * 1024 * 1024
    path = original.with_suffix(suffix)
    original.rename(path)
    monkeypatch.setattr(Path, "stat", lambda _: SimpleNamespace(st_size=size))
    if valid:
        assert probe(path) == (1920.0, 1080.0, 30.0)
    else:
        monkeypatch.setattr(
            "subprocess.run", lambda *a, **kw: pytest.fail("invalid file must not run ffprobe")
        )
        with pytest.raises(ValueError, match="^invalid_file_size_or_extension$"):
            probe(path)


def test_probe_sanitizes_missing_file(original, monkeypatch):
    from social.media import probe

    original.unlink()
    monkeypatch.setattr(
        "subprocess.run", lambda *a, **kw: pytest.fail("missing file must not run ffprobe")
    )
    with pytest.raises(ValueError, match="^invalid_media$"):
        probe(original)


@pytest.mark.parametrize("failure", ["timeout", "process", "missing_binary"])
def test_probe_sanitizes_subprocess_failures(original, monkeypatch, failure):
    import subprocess

    from social.media import probe

    failures = {
        "timeout": subprocess.TimeoutExpired("private-secret", 30, stderr="private-secret"),
        "process": subprocess.CalledProcessError(1, "private-secret", stderr="private-secret"),
        "missing_binary": OSError("private-secret"),
    }

    def fail(*a, **kw):
        raise failures[failure]

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(ValueError, match="^invalid_media$") as error:
        probe(original)
    assert error.value.__suppress_context__
    assert error.value.__cause__ is None


@pytest.mark.parametrize("stdout", ["private-secret", "{}", "null", "[]", '{"streams":null}'])
def test_probe_sanitizes_malformed_probe_output(original, monkeypatch, stdout):
    from social.media import probe

    monkeypatch.setattr("subprocess.run", lambda *a, **kw: SimpleNamespace(stdout=stdout))
    with pytest.raises(ValueError, match="^invalid_media$"):
        probe(original)


def test_probe_invocation_has_timeout_without_shell(original, metadata, monkeypatch):
    from social.media import probe

    monkeypatch.setenv("FFPROBE_BIN", "custom ffprobe.exe")
    seen = []

    def run(command, **kwargs):
        seen.append((command, kwargs))
        return SimpleNamespace(stdout=json.dumps(metadata))

    monkeypatch.setattr("subprocess.run", run)
    probe(original)
    assert seen == [
        (
            [
                "custom ffprobe.exe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(original.resolve()),
            ],
            {"capture_output": True, "text": True, "check": True, "timeout": 30, "shell": False},
        )
    ]


@pytest.mark.parametrize(
    "geometry,want",
    [
        ((1920, 1080, 30), "photo"),
        ((1920, 1080, 600), "photo"),
        ((1080, 1920, 600), "video"),
        ((1080, 1920, 1800), "video"),
        ((1080, 1080, 180), "video"),
        ((1080, 1080, 181), "skip"),
    ],
)
def test_geometry_routes_to_one_delivery_kind(geometry, want):
    from social.media import route_for_geometry

    assert route_for_geometry(*geometry) == want


@pytest.mark.parametrize(
    "geometry",
    [
        (0, 1920, 30),
        (-1080, 1920, 30),
        (1080, 0, 30),
        (float("nan"), 1920, 30),
        (1080, float("inf"), 30),
        (1920, 1080, float("nan")),
        (1080, 1920, 0),
        (1080, 1920, -1),
        (1080, 1920, 1801),
    ],
)
def test_invalid_geometry_is_neither_eligible_nor_routable(geometry):
    from social.media import eligible, route_for_geometry

    assert eligible(*geometry) is False
    assert route_for_geometry(*geometry) == "skip"


def test_probe_returns_display_geometry(original, metadata):
    from social.media import probe

    assert probe(original) == (1920.0, 1080.0, 30.0)


@pytest.mark.parametrize(
    "width,height,duration,want",
    [
        (1080, 1920, 60, True),
        (1080, 1920, 600, True),
        (1080, 1080, 180, True),
        (1080, 1080, 181, False),
        (1920, 1080, 30, False),
    ],
)
def test_editorial_eligibility(width, height, duration, want):
    from social.media import eligible

    assert eligible(width, height, duration) is want
