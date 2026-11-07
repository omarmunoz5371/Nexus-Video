"""Shared pytest fixtures for Nexus Video tests."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Allow importing nexus_video without installing it
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent))

from nexus_video.detect import DisplayInfo


# ---------------------------------------------------------------------------
# Marks
# ---------------------------------------------------------------------------

HAVE_FFMPEG  = shutil.which("ffmpeg") is not None
HAVE_FFPROBE = shutil.which("ffprobe") is not None

needs_ffmpeg  = pytest.mark.skipif(not HAVE_FFMPEG,  reason="ffmpeg not installed")
needs_ffprobe = pytest.mark.skipif(not HAVE_FFPROBE, reason="ffprobe not installed")


# ---------------------------------------------------------------------------
# Standard display fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def display_800x480() -> DisplayInfo:
    return DisplayInfo(width=800, height=480, bpp=16, stride=1600)


@pytest.fixture()
def display_1024x600() -> DisplayInfo:
    return DisplayInfo(width=1024, height=600, bpp=16, stride=2048)


# ---------------------------------------------------------------------------
# Minimal valid pack directory
# ---------------------------------------------------------------------------

def _make_minimal_video(path: Path, duration: float = 1.0, size: str = "320x240") -> None:
    """Generate a minimal synthetic H.264 MP4 for use as a test fixture."""
    cmd = [
        "ffmpeg", "-y", "-nostdin", "-v", "error",
        "-f", "lavfi",
        "-i", f"testsrc=duration={duration}:size={size}:rate=24",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"Could not generate test fixture {path}: {result.stderr.decode()}")


@pytest.fixture()
def valid_pack_dir(tmp_path: Path) -> Path:
    """A pack directory with a valid pack.json, intro.mp4, and loop.mp4."""
    pack = tmp_path / "test_pack"
    pack.mkdir()

    meta = {
        "id": "test_pack", "name": "Test Pack",
        "type": "custom", "version": "1.0.0",
        "description": "Test fixture pack",
        "intro_duration": 1, "loop_duration": 1,
        "scale_mode": "fit", "trademark_notice": None,
        "author": None, "distribution": "test",
    }
    (pack / "pack.json").write_text(json.dumps(meta))

    if HAVE_FFMPEG:
        _make_minimal_video(pack / "intro.mp4", duration=1.0)
        _make_minimal_video(pack / "loop.mp4",  duration=1.0)
    # If ffmpeg is unavailable, video files are absent; tests that need them are skipped.

    return pack


@pytest.fixture()
def invalid_video_file(tmp_path: Path) -> Path:
    """A file named .mp4 that contains text, not video data."""
    p = tmp_path / "fake.mp4"
    p.write_text("This is not a video file.\n")
    return p


@pytest.fixture()
def empty_video_file(tmp_path: Path) -> Path:
    """An empty file named .mp4."""
    p = tmp_path / "empty.mp4"
    p.write_bytes(b"")
    return p


@pytest.fixture()
def corrupt_video_file(tmp_path: Path) -> Path:
    """A file named .mp4 that starts with an MP4 magic marker but is otherwise corrupt."""
    p = tmp_path / "corrupt.mp4"
    # ftyp box start: 32-byte header marker + garbage
    p.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\xff" * 50)
    return p
