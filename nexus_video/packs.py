"""Pack discovery, validation, and manifest generation."""

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .config import (
    BUILTIN_DIR, CUSTOM_DIR,
    DURATION_TOLERANCE, INTRO_FILENAME, LOOP_FILENAME,
    MANIFEST_SCHEMA_VERSION, MIN_VIDEO_DURATION,
    PACK_META_FILE, RECOMMENDED_INTRO_DURATION, RECOMMENDED_LOOP_DURATION,
    SUPPORTED_VIDEO_EXTS,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

REQUIRED_META_FIELDS = ("id", "name", "type", "version")


@dataclass
class VideoInfo:
    duration:  float
    width:     int
    height:    int
    codec:     str
    has_audio: bool
    raw:       dict = field(repr=False, default_factory=dict)


@dataclass
class ValidationResult:
    valid:       bool
    errors:      list[str] = field(default_factory=list)
    warnings:    list[str] = field(default_factory=list)
    intro_info:  Optional[VideoInfo] = None
    loop_info:   Optional[VideoInfo] = None

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.valid = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


@dataclass
class PackInfo:
    pack_dir:   Path
    meta:       dict[str, Any]
    validation: ValidationResult

    @property
    def pack_id(self) -> str:
        return self.meta.get("id", self.pack_dir.name)

    @property
    def name(self) -> str:
        return self.meta.get("name", self.pack_id)

    @property
    def pack_type(self) -> str:
        return self.meta.get("type", "custom")


# ---------------------------------------------------------------------------
# ffprobe helpers
# ---------------------------------------------------------------------------

class VideoProbeError(ValueError):
    pass


def probe_video(path: Path) -> VideoInfo:
    """Run ffprobe on *path* and return a VideoInfo.

    Raises VideoProbeError if ffprobe cannot read the file or no video stream
    is found.
    """
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-show_format",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except FileNotFoundError as exc:
        raise VideoProbeError("ffprobe not found — install ffmpeg") from exc
    except subprocess.TimeoutExpired as exc:
        raise VideoProbeError(f"ffprobe timed out on {path}") from exc

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise VideoProbeError(
            f"ffprobe failed on {path} (exit {result.returncode}): {stderr}"
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise VideoProbeError(f"ffprobe returned invalid JSON for {path}") from exc

    video_streams = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    if not video_streams:
        raise VideoProbeError(f"No video stream found in {path}")

    vs = video_streams[0]

    # Duration from format (most reliable) or from stream
    fmt     = data.get("format", {})
    duration_str = fmt.get("duration") or vs.get("duration", "0")
    try:
        duration = float(duration_str)
    except (TypeError, ValueError):
        duration = 0.0

    has_audio = any(
        s.get("codec_type") == "audio" for s in data.get("streams", [])
    )

    return VideoInfo(
        duration=duration,
        width=int(vs.get("width", 0)),
        height=int(vs.get("height", 0)),
        codec=vs.get("codec_name", "unknown"),
        has_audio=has_audio,
        raw=data,
    )


# ---------------------------------------------------------------------------
# Pack validation
# ---------------------------------------------------------------------------

def _validate_meta(pack_dir: Path, result: ValidationResult) -> dict:
    meta_path = pack_dir / PACK_META_FILE
    if not meta_path.exists():
        result.add_error(f"Missing {PACK_META_FILE}")
        return {}
    try:
        meta = json.loads(meta_path.read_text())
    except json.JSONDecodeError as exc:
        result.add_error(f"Invalid JSON in {PACK_META_FILE}: {exc}")
        return {}

    for field_name in REQUIRED_META_FIELDS:
        if field_name not in meta:
            result.add_error(f"{PACK_META_FILE} missing required field: '{field_name}'")

    return meta


def _validate_video_file(
    path: Path,
    label: str,
    recommended_duration: float,
    result: ValidationResult,
) -> Optional[VideoInfo]:
    if not path.exists():
        result.add_error(f"Missing {label}: {path.name}")
        return None

    if path.suffix.lower() not in SUPPORTED_VIDEO_EXTS:
        result.add_error(
            f"{label} has unsupported extension '{path.suffix}'; "
            f"expected one of {sorted(SUPPORTED_VIDEO_EXTS)}"
        )
        return None

    try:
        info = probe_video(path)
    except VideoProbeError as exc:
        result.add_error(f"{label} probe failed: {exc}")
        return None

    if info.duration < MIN_VIDEO_DURATION:
        result.add_error(
            f"{label} duration {info.duration:.2f}s is below minimum "
            f"{MIN_VIDEO_DURATION}s"
        )

    dev = abs(info.duration - recommended_duration)
    if dev > DURATION_TOLERANCE:
        result.add_warning(
            f"{label} duration {info.duration:.1f}s differs from recommended "
            f"{recommended_duration:.0f}s by {dev:.1f}s"
        )

    if info.width == 0 or info.height == 0:
        result.add_error(f"{label} has zero-dimension video stream ({info.width}x{info.height})")

    if info.has_audio:
        result.add_warning(
            f"{label} contains an audio track — it will be stripped during conversion"
        )

    return info


def validate_pack(pack_dir: Path) -> ValidationResult:
    """Validate a pack directory.

    Checks:
    - pack.json exists, is valid JSON, has required fields
    - intro.mp4 and loop.mp4 exist and are valid video files (via ffprobe)
    - Duration is within tolerance of recommended values
    - No zero-dimension video streams
    """
    result = ValidationResult(valid=True)

    if not pack_dir.is_dir():
        result.add_error(f"Pack directory not found: {pack_dir}")
        return result

    _validate_meta(pack_dir, result)

    result.intro_info = _validate_video_file(
        pack_dir / INTRO_FILENAME,
        label="intro.mp4",
        recommended_duration=RECOMMENDED_INTRO_DURATION,
        result=result,
    )
    result.loop_info = _validate_video_file(
        pack_dir / LOOP_FILENAME,
        label="loop.mp4",
        recommended_duration=RECOMMENDED_LOOP_DURATION,
        result=result,
    )

    return result


# ---------------------------------------------------------------------------
# Pack discovery
# ---------------------------------------------------------------------------

def _load_pack(pack_dir: Path, pack_type_hint: str) -> Optional[PackInfo]:
    meta_path = pack_dir / PACK_META_FILE
    if not meta_path.exists():
        log.debug("Skipping %s — no pack.json", pack_dir)
        return None

    try:
        meta = json.loads(meta_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not load %s: %s", meta_path, exc)
        return None

    if "type" not in meta:
        meta["type"] = pack_type_hint

    return PackInfo(pack_dir=pack_dir, meta=meta, validation=ValidationResult(valid=True))


def discover_packs(
    builtin_dir: Path = BUILTIN_DIR,
    custom_dir:  Path = CUSTOM_DIR,
) -> list[PackInfo]:
    """Return all packs from builtin and custom directories.

    Builtin packs are discovered first. Custom packs follow. Within each
    directory, packs are sorted alphabetically by directory name.

    A directory is a pack candidate if it contains a pack.json file.
    Missing video files do NOT prevent discovery — validation is a separate
    step (call validate_pack for each PackInfo.pack_dir).
    """
    packs: list[PackInfo] = []

    for src_dir, type_hint in ((builtin_dir, "builtin"), (custom_dir, "custom")):
        if not src_dir.is_dir():
            log.debug("Pack directory %s does not exist — skipping", src_dir)
            continue
        for entry in sorted(src_dir.iterdir()):
            if not entry.is_dir():
                continue
            pack = _load_pack(entry, type_hint)
            if pack is not None:
                packs.append(pack)
                log.debug("Discovered %s pack: %s", type_hint, pack.pack_id)

    log.info("Discovered %d pack(s): %s", len(packs), [p.pack_id for p in packs])
    return packs


# ---------------------------------------------------------------------------
# Manifest generation
# ---------------------------------------------------------------------------

def _pack_to_manifest_entry(pack: PackInfo) -> dict:
    return {
        "id":           pack.pack_id,
        "name":         pack.name,
        "type":         pack.pack_type,
        "pack_dir":     str(pack.pack_dir),
        "valid":        pack.validation.valid,
        "errors":       pack.validation.errors,
        "warnings":     pack.validation.warnings,
        "meta":         pack.meta,
    }


def generate_manifest(
    builtin_dir: Path = BUILTIN_DIR,
    custom_dir:  Path = CUSTOM_DIR,
    validate: bool = True,
) -> dict:
    """Discover all packs and return a manifest dict.

    If validate=True, runs validate_pack for each discovered pack and stores
    the result in the manifest. This requires ffprobe.
    """
    packs = discover_packs(builtin_dir=builtin_dir, custom_dir=custom_dir)

    if validate:
        for pack in packs:
            pack.validation = validate_pack(pack.pack_dir)

    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "pack_count":     len(packs),
        "packs":          [_pack_to_manifest_entry(p) for p in packs],
    }
