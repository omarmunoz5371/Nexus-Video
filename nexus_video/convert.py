"""ffmpeg conversion pipeline: source video → built pack media."""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .config import (
    BUILD_DIR, DEFAULT_SCALE, INTRO_FILENAME,
    LOOP_FILENAME, SCALE_MODES, STILL_FILENAME,
)
from .detect import DisplayInfo

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scale filter strings
# ---------------------------------------------------------------------------

def scale_filter(mode: str, width: int, height: int) -> str:
    """Return an ffmpeg -vf filter string for the given scale mode.

    fit     — letterbox/pillarbox: whole frame visible, black bars fill gaps
    fill    — zoom-and-crop: fills screen, crops excess, no black bars
    stretch — scale to exact dimensions, ignores source aspect ratio
    """
    if mode not in SCALE_MODES:
        raise ValueError(f"scale_mode must be one of {SCALE_MODES}, got {mode!r}")

    w, h = width, height
    if mode == "fit":
        return (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
        )
    if mode == "fill":
        return (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h}"
        )
    # stretch
    return f"scale={w}:{h}"


# ---------------------------------------------------------------------------
# Conversion errors
# ---------------------------------------------------------------------------

class ConversionError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Single-video conversion
# ---------------------------------------------------------------------------

def convert_video(
    src: Path,
    dst: Path,
    display_info: DisplayInfo,
    scale_mode: str = DEFAULT_SCALE,
    duration: Optional[float] = None,
    crf: int = 18,
    threads: int = 2,
) -> None:
    """Convert *src* to H.264 MP4 at display resolution using *scale_mode*.

    Args:
        src:          Source video file.
        dst:          Destination MP4 (created or overwritten).
        display_info: Target resolution and bpp.
        scale_mode:   One of "fit", "fill", "stretch".
        duration:     If set, trim the output to this many seconds.
        crf:          H.264 CRF quality (lower = better; 18 is visually lossless).
        threads:      Number of ffmpeg threads (keep ≤ 2 on Pi to leave CPU headroom).

    Raises ConversionError if ffmpeg exits non-zero or is not found.
    """
    if not src.exists():
        raise ConversionError(f"Source file not found: {src}")

    dst.parent.mkdir(parents=True, exist_ok=True)

    vf = scale_filter(scale_mode, display_info.width, display_info.height)

    cmd = [
        "ffmpeg", "-y", "-nostdin", "-v", "error",
        "-threads", str(threads),
        "-i", str(src),
        "-an",           # strip audio
        "-vf", vf,
        "-c:v", "libx264",
        "-profile:v", "high",
        "-preset", "slow",
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
    ]

    if duration is not None:
        cmd += ["-t", str(duration)]

    cmd.append(str(dst))

    log.info("Converting %s → %s [%s %dx%d]", src.name, dst.name, scale_mode,
             display_info.width, display_info.height)
    log.debug("ffmpeg cmd: %s", " ".join(cmd))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except FileNotFoundError as exc:
        raise ConversionError("ffmpeg not found — install ffmpeg") from exc
    except subprocess.TimeoutExpired as exc:
        raise ConversionError(f"ffmpeg timed out converting {src}") from exc

    if result.returncode != 0:
        raise ConversionError(
            f"ffmpeg failed (exit {result.returncode}) converting {src}:\n"
            + result.stderr.strip()
        )

    log.info("Conversion complete: %s (%.1f KB)", dst.name, dst.stat().st_size / 1024)


# ---------------------------------------------------------------------------
# Still frame generation
# ---------------------------------------------------------------------------

def generate_still(
    output_dir: Path,
    display_info: DisplayInfo,
    source: Optional[Path] = None,
    timestamp: float = 0.5,
) -> Path:
    """Generate a still.rgb565 file for the framebuffer hold-still state.

    If *source* is given, extracts the frame at *timestamp* seconds and
    converts it to RGB565. Otherwise writes a solid black frame.

    Returns the path to the generated file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    still_path = output_dir / STILL_FILENAME
    expected_bytes = display_info.width * display_info.height * 2  # 16-bit

    if source is not None and source.exists():
        cmd = [
            "ffmpeg", "-y", "-nostdin", "-v", "error",
            "-ss", str(timestamp),
            "-i", str(source),
            "-vframes", "1",
            "-vf", scale_filter("fit", display_info.width, display_info.height),
            "-f", "rawvideo",
            "-pix_fmt", "rgb565le",
            str(still_path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode == 0 and still_path.exists():
                actual = still_path.stat().st_size
                if actual == expected_bytes:
                    log.info("Generated still from %s (%d bytes)", source.name, actual)
                    return still_path
                log.warning(
                    "Still frame size mismatch: got %d, expected %d — falling back to black",
                    actual, expected_bytes,
                )
        except (subprocess.TimeoutExpired, OSError) as exc:
            log.warning("Still frame extraction failed (%s) — using black frame", exc)

    # Fallback: write solid black frame
    still_path.write_bytes(bytes(expected_bytes))
    log.info("Generated black still frame (%d bytes)", expected_bytes)
    return still_path


# ---------------------------------------------------------------------------
# Full-pack conversion
# ---------------------------------------------------------------------------

def convert_pack(
    pack_dir: Path,
    output_dir: Optional[Path] = None,
    display_info: Optional[DisplayInfo] = None,
    scale_mode: str = DEFAULT_SCALE,
) -> Path:
    """Convert a full pack (intro + loop + still) into *output_dir*.

    pack_dir must contain intro.mp4 and loop.mp4.
    output_dir defaults to BUILD_DIR / <pack_dir.name>.
    display_info defaults to 800×480 16-bit (the Pi 4 default).

    Returns the output directory path.
    Raises ConversionError on any failure.
    """
    if display_info is None:
        from .detect import DisplayInfo as _DI
        from .config import FALLBACK_WIDTH, FALLBACK_HEIGHT, FALLBACK_BPP, FALLBACK_STRIDE
        display_info = _DI(
            width=FALLBACK_WIDTH, height=FALLBACK_HEIGHT,
            bpp=FALLBACK_BPP, stride=FALLBACK_STRIDE,
        )

    if output_dir is None:
        output_dir = BUILD_DIR / pack_dir.name

    output_dir.mkdir(parents=True, exist_ok=True)

    src_intro = pack_dir / INTRO_FILENAME
    src_loop  = pack_dir / LOOP_FILENAME

    if not src_intro.exists():
        raise ConversionError(f"intro.mp4 not found in {pack_dir}")
    if not src_loop.exists():
        raise ConversionError(f"loop.mp4 not found in {pack_dir}")

    convert_video(src_intro, output_dir / INTRO_FILENAME, display_info, scale_mode)
    convert_video(src_loop,  output_dir / LOOP_FILENAME,  display_info, scale_mode)
    generate_still(output_dir, display_info, source=output_dir / INTRO_FILENAME)

    # Write a build manifest alongside the output
    import json, datetime
    build_meta = {
        "source_pack":   str(pack_dir),
        "scale_mode":    scale_mode,
        "width":         display_info.width,
        "height":        display_info.height,
        "bpp":           display_info.bpp,
        "built_at":      datetime.datetime.utcnow().isoformat() + "Z",
    }
    (output_dir / "build_meta.json").write_text(json.dumps(build_meta, indent=2))
    log.info("Pack '%s' converted to %s", pack_dir.name, output_dir)
    return output_dir


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def validate_output(output_dir: Path, display_info: DisplayInfo) -> list[str]:
    """Check that a converted pack output is complete and correctly sized.

    Returns a list of error strings (empty list = all good).
    """
    errors: list[str] = []
    expected_still = display_info.width * display_info.height * 2

    for filename in (INTRO_FILENAME, LOOP_FILENAME):
        p = output_dir / filename
        if not p.exists():
            errors.append(f"Missing output file: {filename}")
        elif p.stat().st_size == 0:
            errors.append(f"Empty output file: {filename}")

    still = output_dir / STILL_FILENAME
    if not still.exists():
        errors.append(f"Missing {STILL_FILENAME}")
    elif still.stat().st_size != expected_still:
        errors.append(
            f"{STILL_FILENAME} is {still.stat().st_size} bytes, "
            f"expected {expected_still} ({display_info.width}×{display_info.height}×2)"
        )

    return errors
