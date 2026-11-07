"""Tests for nexus_video.detect — display detection from sysfs."""

from pathlib import Path
from unittest.mock import patch, mock_open

import pytest

from nexus_video.detect import (
    DisplayInfo, DisplayDetectionError, detect_display,
)
from nexus_video.config import (
    FALLBACK_BPP, FALLBACK_HEIGHT, FALLBACK_STRIDE, FALLBACK_WIDTH,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sysfs(tmp_path: Path, virtual_size: str, bpp: str, stride: str) -> Path:
    sysfs = tmp_path / "fb0"
    sysfs.mkdir()
    (sysfs / "virtual_size").write_text(virtual_size)
    (sysfs / "bits_per_pixel").write_text(bpp)
    (sysfs / "stride").write_text(stride)
    return sysfs


# ---------------------------------------------------------------------------
# Normal detection
# ---------------------------------------------------------------------------

def test_detect_reads_800x480_16bpp(tmp_path):
    sysfs = _make_sysfs(tmp_path, "800,480", "16", "1600")
    info = detect_display(sysfs_dir=sysfs)
    assert info.width == 800
    assert info.height == 480
    assert info.bpp == 16
    assert info.stride == 1600


def test_detect_reads_1024x600_16bpp(tmp_path):
    sysfs = _make_sysfs(tmp_path, "1024,600", "16", "2048")
    info = detect_display(sysfs_dir=sysfs)
    assert info.width == 1024
    assert info.height == 600
    assert info.bpp == 16


def test_detect_reads_32bpp(tmp_path):
    sysfs = _make_sysfs(tmp_path, "800,480", "32", "3200")
    info = detect_display(sysfs_dir=sysfs)
    assert info.bpp == 32
    assert info.needs_rgb32_pipeline is True
    assert info.is_supported is False


def test_detect_uses_fb_path_argument(tmp_path):
    sysfs = _make_sysfs(tmp_path, "800,480", "16", "1600")
    info = detect_display(fb_path="/dev/fb1", sysfs_dir=sysfs)
    assert info.fb_path == "/dev/fb1"


# ---------------------------------------------------------------------------
# Fallback when sysfs is absent
# ---------------------------------------------------------------------------

def test_detect_fallback_when_sysfs_missing(tmp_path):
    absent = tmp_path / "nonexistent_fb"
    info = detect_display(sysfs_dir=absent)
    assert info.width  == FALLBACK_WIDTH
    assert info.height == FALLBACK_HEIGHT
    assert info.bpp    == FALLBACK_BPP
    assert info.stride == FALLBACK_STRIDE


# ---------------------------------------------------------------------------
# DisplayInfo computed properties
# ---------------------------------------------------------------------------

def test_display_info_frame_bytes_16bpp():
    info = DisplayInfo(width=800, height=480, bpp=16, stride=1600)
    assert info.frame_bytes == 800 * 480 * 2


def test_display_info_frame_bytes_32bpp():
    info = DisplayInfo(width=800, height=480, bpp=32, stride=3200)
    assert info.frame_bytes == 800 * 480 * 4


def test_display_info_is_supported_16bpp():
    info = DisplayInfo(width=800, height=480, bpp=16, stride=1600)
    assert info.is_supported is True


def test_display_info_is_not_supported_32bpp():
    info = DisplayInfo(width=800, height=480, bpp=32, stride=3200)
    assert info.is_supported is False
    assert info.needs_rgb32_pipeline is True


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

def test_detect_raises_on_malformed_virtual_size(tmp_path):
    sysfs = _make_sysfs(tmp_path, "800x480", "16", "1600")  # 'x' not ','
    with pytest.raises(DisplayDetectionError, match="Malformed sysfs"):
        detect_display(sysfs_dir=sysfs)


def test_detect_raises_on_non_numeric_bpp(tmp_path):
    sysfs = _make_sysfs(tmp_path, "800,480", "sixteen", "1600")
    with pytest.raises(DisplayDetectionError, match="Malformed sysfs"):
        detect_display(sysfs_dir=sysfs)


def test_detect_raises_on_missing_bits_per_pixel_file(tmp_path):
    sysfs = tmp_path / "fb0"
    sysfs.mkdir()
    (sysfs / "virtual_size").write_text("800,480")
    (sysfs / "stride").write_text("1600")
    # bits_per_pixel intentionally missing
    with pytest.raises(DisplayDetectionError, match="Cannot read sysfs"):
        detect_display(sysfs_dir=sysfs)
