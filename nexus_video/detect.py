"""Framebuffer display detection via /sys/class/graphics/fb0."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import (
    DEFAULT_FB_PATH,
    FALLBACK_BPP, FALLBACK_HEIGHT, FALLBACK_STRIDE, FALLBACK_WIDTH,
    SYSFS_FB0_DIR, SUPPORTED_BPP, WARN_BPP,
)

log = logging.getLogger(__name__)


@dataclass
class DisplayInfo:
    width:    int
    height:   int
    bpp:      int
    stride:   int      # bytes per row
    fb_path:  str = DEFAULT_FB_PATH

    @property
    def frame_bytes(self) -> int:
        return self.width * self.height * (self.bpp // 8)

    @property
    def is_supported(self) -> bool:
        return self.bpp in SUPPORTED_BPP

    @property
    def needs_rgb32_pipeline(self) -> bool:
        return self.bpp in WARN_BPP


class DisplayDetectionError(RuntimeError):
    pass


def _read_sysfs(sysfs_dir: Path, name: str) -> str:
    return (sysfs_dir / name).read_text().strip()


def detect_display(
    fb_path: str = DEFAULT_FB_PATH,
    sysfs_dir: Optional[Path] = None,
) -> DisplayInfo:
    """Read display geometry from sysfs.

    Returns a DisplayInfo populated from /sys/class/graphics/fb0 (or the
    override sysfs_dir). Falls back to FALLBACK_* constants and logs a warning
    when sysfs is unavailable so callers on non-Pi development hosts still work.

    Raises DisplayDetectionError only on malformed (non-numeric) sysfs values.
    """
    sysfs = sysfs_dir if sysfs_dir is not None else SYSFS_FB0_DIR

    if not sysfs.exists():
        log.warning(
            "sysfs %s not found — using fallback %dx%d bpp=%d",
            sysfs, FALLBACK_WIDTH, FALLBACK_HEIGHT, FALLBACK_BPP,
        )
        return DisplayInfo(
            width=FALLBACK_WIDTH, height=FALLBACK_HEIGHT,
            bpp=FALLBACK_BPP, stride=FALLBACK_STRIDE,
            fb_path=fb_path,
        )

    try:
        raw_size   = _read_sysfs(sysfs, "virtual_size")   # "800,480"
        raw_bpp    = _read_sysfs(sysfs, "bits_per_pixel")  # "16"
        raw_stride = _read_sysfs(sysfs, "stride")          # "1600"
    except OSError as exc:
        raise DisplayDetectionError(f"Cannot read sysfs {sysfs}: {exc}") from exc

    try:
        w_str, h_str = raw_size.split(",")
        width  = int(w_str)
        height = int(h_str)
        bpp    = int(raw_bpp)
        stride = int(raw_stride)
    except ValueError as exc:
        raise DisplayDetectionError(
            f"Malformed sysfs values in {sysfs}: size={raw_size!r} "
            f"bpp={raw_bpp!r} stride={raw_stride!r}"
        ) from exc

    info = DisplayInfo(width=width, height=height, bpp=bpp, stride=stride, fb_path=fb_path)

    if info.needs_rgb32_pipeline:
        log.warning(
            "Display is %d-bit (%dx%d). The current pipeline only supports 16-bit RGB565. "
            "Phase 2 does not support this framebuffer yet.",
            bpp, width, height,
        )
    elif not info.is_supported:
        log.warning("Unsupported bpp=%d on %dx%d display.", bpp, width, height)
    else:
        log.info("Display detected: %dx%d bpp=%d stride=%d (%s)", width, height, bpp, stride, fb_path)

    return info
