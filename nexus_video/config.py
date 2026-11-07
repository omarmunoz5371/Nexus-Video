"""Central configuration and path constants for Nexus Video."""

import pathlib

# ---------------------------------------------------------------------------
# Project root (resolved from this file's location)
# ---------------------------------------------------------------------------

PROJECT_ROOT = pathlib.Path(__file__).parent.parent.resolve()
PACKS_ROOT   = PROJECT_ROOT / "packs"
BUILTIN_DIR  = PACKS_ROOT / "builtin"
CUSTOM_DIR   = PACKS_ROOT / "custom"
BUILD_DIR    = PROJECT_ROOT / "build"

# ---------------------------------------------------------------------------
# Pack format
# ---------------------------------------------------------------------------

PACK_META_FILE   = "pack.json"
INTRO_FILENAME   = "intro.mp4"
LOOP_FILENAME    = "loop.mp4"
STILL_FILENAME   = "still.rgb565"
MANIFEST_FILE    = "manifest.json"

# Recommended durations (seconds); validation warns if outside these ranges.
RECOMMENDED_INTRO_DURATION = 10.0
RECOMMENDED_LOOP_DURATION  = 5.0
DURATION_TOLERANCE         = 2.0   # ± seconds before warning fires

MIN_VIDEO_DURATION = 0.5           # below this → hard error

SUPPORTED_VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm"}

# ---------------------------------------------------------------------------
# Display / framebuffer
# ---------------------------------------------------------------------------

DEFAULT_FB_PATH  = "/dev/fb0"
SYSFS_FB0_DIR    = pathlib.Path("/sys/class/graphics/fb0")

# Fallback when sysfs is unavailable (e.g. development on a non-Pi host)
FALLBACK_WIDTH   = 800
FALLBACK_HEIGHT  = 480
FALLBACK_BPP     = 16
FALLBACK_STRIDE  = 1600            # = 800 * 2

SUPPORTED_BPP    = {16}            # only RGB565 currently supported
WARN_BPP         = {32}            # detected but not yet supported

# ---------------------------------------------------------------------------
# Scaling
# ---------------------------------------------------------------------------

SCALE_MODES      = ("fit", "fill", "stretch")
DEFAULT_SCALE    = "fit"

# ---------------------------------------------------------------------------
# Splash handover (for documentation / future integration)
# ---------------------------------------------------------------------------

HANDOVER_DIR     = pathlib.Path("/run/nexus-splash")
HANDOVER_PID     = HANDOVER_DIR / "player.pid"
HANDOVER_READY   = HANDOVER_DIR / "ready"
HANDOVER_RELEASED = HANDOVER_DIR / "released"

# RuntimeDirectory= name the systemd unit must declare to create HANDOVER_DIR.
SYSTEMD_RUNTIME_DIR = "nexus-splash"

# ---------------------------------------------------------------------------
# Manifest schema version
# ---------------------------------------------------------------------------

MANIFEST_SCHEMA_VERSION = "1.0"
