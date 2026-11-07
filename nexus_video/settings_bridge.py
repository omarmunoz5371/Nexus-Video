"""Nexus Video settings bridge: read/write video pack selection from Nexus Screen preferences.

Nexus Screen stores its own preferences at ~/.config/nexus-screen/preferences.json.
Nexus Video extends those preferences with two keys:
  startup_video_pack  — pack id string, e.g. "nexus_signature"
  startup_video_scale — scale mode string: "fit", "fill" or "stretch"

The service configuration at ~/nexus-video/config.json (or the dev path) is kept in
sync so the boot service reads it on the next reboot without touching Nexus Screen
internals.
"""
import json
import os
from pathlib import Path

PREFS_PATH = Path(os.path.expanduser("~/.config/nexus-screen/preferences.json"))

PREF_PACK  = "startup_video_pack"
PREF_SCALE = "startup_video_scale"

DEFAULT_PACK  = "nexus_signature"
DEFAULT_SCALE = "fit"
VALID_SCALES  = ("fit", "fill", "stretch")


def _read_prefs() -> dict:
    if PREFS_PATH.exists():
        try:
            with open(PREFS_PATH) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            pass
    return {}


def _write_prefs(prefs: dict) -> None:
    PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PREFS_PATH, "w") as fh:
        json.dump(prefs, fh, indent=2)


def get_selection() -> tuple[str, str]:
    """Return (pack_id, scale_mode) from preferences, with defaults."""
    prefs = _read_prefs()
    pack  = prefs.get(PREF_PACK, DEFAULT_PACK)
    scale = prefs.get(PREF_SCALE, DEFAULT_SCALE)
    if scale not in VALID_SCALES:
        scale = DEFAULT_SCALE
    return pack, scale


def set_selection(pack_id: str, scale_mode: str, service_config_path: Path | None = None) -> None:
    """Persist pack selection to preferences and optionally to the service config file."""
    if scale_mode not in VALID_SCALES:
        raise ValueError(f"Invalid scale mode: {scale_mode!r} (must be one of {VALID_SCALES})")
    prefs = _read_prefs()
    prefs[PREF_PACK]  = pack_id
    prefs[PREF_SCALE] = scale_mode
    _write_prefs(prefs)
    if service_config_path is not None:
        _write_service_config(pack_id, scale_mode, service_config_path)


def _write_service_config(pack_id: str, scale_mode: str, config_path: Path) -> None:
    """Write ~/nexus-video/config.json (read by the boot service on the next start)."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as fh:
        json.dump({"pack": pack_id, "scale": scale_mode}, fh, indent=2)


def build_is_ready(build_dir: Path, pack_id: str) -> bool:
    """True when the pack has a complete converted output (intro + loop + still)."""
    pack_build = build_dir / pack_id
    return all(
        (pack_build / name).exists()
        for name in ("intro.mp4", "loop.mp4", "still.rgb565")
    )


def active_pack_path(build_dir: Path, pack_id: str) -> Path:
    """Path to the converted output directory for pack_id."""
    return build_dir / pack_id
