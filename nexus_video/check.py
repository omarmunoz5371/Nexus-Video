"""Automated quality checks for source videos, loops, and converted output."""

import logging
import math
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .config import (
    DURATION_TOLERANCE, INTRO_FILENAME, LOOP_FILENAME,
    MIN_VIDEO_DURATION, RECOMMENDED_INTRO_DURATION,
    RECOMMENDED_LOOP_DURATION, STILL_FILENAME,
)
from .detect import DisplayInfo
from .packs import VideoInfo, VideoProbeError, probe_video

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Check result
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    name:     str
    passed:   bool
    actual:   Any
    expected: Any
    message:  str
    severity: str = "error"   # "error" | "warning" | "info"

    def __str__(self) -> str:
        status = "PASS" if self.passed else self.severity.upper()
        return f"[{status}] {self.name}: {self.message}"


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_codec(path: Path, expected: str = "h264") -> CheckResult:
    """Verify the video stream uses the expected codec."""
    try:
        info = probe_video(path)
    except VideoProbeError as exc:
        return CheckResult("codec", False, None, expected, str(exc))
    match = info.codec.lower() == expected.lower()
    return CheckResult(
        name="codec",
        passed=match,
        actual=info.codec,
        expected=expected,
        message=f"{info.codec} {'==' if match else '!='} {expected}",
        severity="error",
    )


def check_resolution(path: Path, expected_w: int, expected_h: int) -> CheckResult:
    """Verify video dimensions exactly match expected values."""
    try:
        info = probe_video(path)
    except VideoProbeError as exc:
        return CheckResult("resolution", False, None, f"{expected_w}x{expected_h}", str(exc))
    actual = f"{info.width}x{info.height}"
    expected = f"{expected_w}x{expected_h}"
    match = info.width == expected_w and info.height == expected_h
    return CheckResult(
        name="resolution",
        passed=match,
        actual=actual,
        expected=expected,
        message=f"{actual} {'==' if match else '!='} {expected}",
        severity="error",
    )


def check_duration(
    path: Path,
    expected: float,
    tolerance: float = DURATION_TOLERANCE,
) -> CheckResult:
    """Check video duration is within tolerance of expected."""
    try:
        info = probe_video(path)
    except VideoProbeError as exc:
        return CheckResult("duration", False, None, expected, str(exc))
    dev = abs(info.duration - expected)
    passed = dev <= tolerance
    return CheckResult(
        name="duration",
        passed=passed,
        actual=round(info.duration, 2),
        expected=f"{expected}±{tolerance}",
        message=f"{info.duration:.2f}s {'within' if passed else 'outside'} {expected}±{tolerance}s",
        severity="warning" if not passed else "info",
    )


def check_frame_count(
    path: Path,
    expected_fps: float = 24.0,
    expected_duration: Optional[float] = None,
    tolerance: int = 2,
) -> CheckResult:
    """Check the video has approximately the expected frame count.

    Expected frames = floor(expected_duration × expected_fps).
    If expected_duration is None, uses the probed duration.
    """
    try:
        info = probe_video(path)
    except VideoProbeError as exc:
        return CheckResult("frame_count", False, None, "unknown", str(exc))

    dur = expected_duration if expected_duration is not None else info.duration
    expected_frames = int(dur * expected_fps)

    # nb_frames from ffprobe; fall back to duration × fps
    raw_nb = info.raw.get("streams", [{}])[0].get("nb_frames")
    if raw_nb and str(raw_nb).isdigit():
        actual_frames = int(raw_nb)
    else:
        # Probe r_frame_rate and compute
        rfps_str = info.raw.get("streams", [{}])[0].get("r_frame_rate", "24/1")
        try:
            num, den = map(int, rfps_str.split("/"))
            actual_frames = round(info.duration * num / den)
        except (ValueError, ZeroDivisionError):
            actual_frames = round(info.duration * expected_fps)

    passed = abs(actual_frames - expected_frames) <= tolerance
    return CheckResult(
        name="frame_count",
        passed=passed,
        actual=actual_frames,
        expected=f"{expected_frames}±{tolerance}",
        message=f"{actual_frames} frames {'≈' if passed else '≠'} expected {expected_frames}±{tolerance}",
        severity="warning" if not passed else "info",
    )


def check_has_no_audio(path: Path) -> CheckResult:
    """Verify the file has no audio stream (required for playback copies)."""
    try:
        info = probe_video(path)
    except VideoProbeError as exc:
        return CheckResult("no_audio", False, None, "no audio", str(exc))
    has_audio = info.has_audio
    return CheckResult(
        name="no_audio",
        passed=not has_audio,
        actual="has audio" if has_audio else "no audio",
        expected="no audio",
        message="Audio track present — will be stripped during conversion" if has_audio else "No audio track",
        severity="warning" if has_audio else "info",
    )


def check_pix_fmt(path: Path, expected: str = "yuv420p") -> CheckResult:
    """Check pixel format of the video stream."""
    try:
        info = probe_video(path)
    except VideoProbeError as exc:
        return CheckResult("pix_fmt", False, None, expected, str(exc))
    streams = info.raw.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    actual = video_streams[0].get("pix_fmt", "unknown") if video_streams else "unknown"
    match = actual == expected
    return CheckResult(
        name="pix_fmt",
        passed=match,
        actual=actual,
        expected=expected,
        message=f"pixel format {actual} {'==' if match else '!='} {expected}",
        severity="warning" if not match else "info",
    )


# ---------------------------------------------------------------------------
# Loop continuity check
# ---------------------------------------------------------------------------

def _extract_frame_rgb24(path: Path, seek_to_start: bool, tmpdir: Path) -> bytes:
    """Extract first (seek_to_start=True) or last frame as raw RGB24 bytes."""
    out = tmpdir / ("first.raw" if seek_to_start else "last.raw")
    if seek_to_start:
        cmd = [
            "ffmpeg", "-y", "-nostdin", "-v", "error",
            "-i", str(path), "-vframes", "1",
            "-f", "rawvideo", "-pix_fmt", "rgb24", str(out),
        ]
    else:
        # Reverse the whole video and take the first decoded frame = last frame
        cmd = [
            "ffmpeg", "-y", "-nostdin", "-v", "error",
            "-i", str(path), "-vf", "reverse", "-vframes", "1",
            "-f", "rawvideo", "-pix_fmt", "rgb24", str(out),
        ]
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"Frame extraction failed: {result.stderr.decode()}")
    return out.read_bytes()


def _psnr(a: bytes, b: bytes) -> float:
    """Compute PSNR between two equal-length raw RGB24 byte sequences."""
    if len(a) != len(b):
        raise ValueError(f"Frame size mismatch: {len(a)} vs {len(b)}")
    if a == b:
        return float("inf")
    n = len(a)
    mse = sum((x - y) ** 2 for x, y in zip(a, b)) / n
    return 10.0 * math.log10(255.0 ** 2 / mse)


def check_loop_continuity(
    path: Path,
    psnr_threshold_seamless: float = 35.0,
    psnr_threshold_acceptable: float = 25.0,
) -> CheckResult:
    """Compare the first and last frames of a loop video and report PSNR.

    PSNR ≥ psnr_threshold_seamless  → PASS (visually seamless)
    PSNR ≥ psnr_threshold_acceptable → WARNING (may have subtle transition)
    PSNR <  psnr_threshold_acceptable → ERROR (visible discontinuity)

    Note: Due to H.264 codec quantization, even a mathematically identical
    palindrome loop will not reach inf PSNR; values ≥ 35 dB are seamless.
    """
    if not path.exists():
        return CheckResult("loop_continuity", False, None, f"≥{psnr_threshold_seamless}dB",
                           f"File not found: {path}")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            first = _extract_frame_rgb24(path, seek_to_start=True,  tmpdir=tmppath)
            last  = _extract_frame_rgb24(path, seek_to_start=False, tmpdir=tmppath)
            psnr = _psnr(first, last)
    except Exception as exc:
        return CheckResult("loop_continuity", False, None, f"≥{psnr_threshold_seamless}dB",
                           f"Frame extraction failed: {exc}")

    psnr_str = f"{psnr:.1f}dB" if psnr != float("inf") else "∞ (identical)"
    threshold_str = f"≥{psnr_threshold_seamless}dB"

    if psnr >= psnr_threshold_seamless:
        return CheckResult("loop_continuity", True, psnr_str, threshold_str,
                           f"PSNR {psnr_str} — seamless", severity="info")
    if psnr >= psnr_threshold_acceptable:
        return CheckResult("loop_continuity", False, psnr_str, threshold_str,
                           f"PSNR {psnr_str} — may have subtle transition", severity="warning")
    return CheckResult("loop_continuity", False, psnr_str, threshold_str,
                       f"PSNR {psnr_str} — visible discontinuity at loop point", severity="error")


# ---------------------------------------------------------------------------
# High-level pack checks
# ---------------------------------------------------------------------------

def check_source_video(path: Path, expected_duration: float = RECOMMENDED_INTRO_DURATION) -> list[CheckResult]:
    """Run all checks expected of an intro source video before conversion."""
    results = [
        check_duration(path, expected_duration),
        check_codec(path),
        check_frame_count(path, expected_fps=24.0, expected_duration=expected_duration),
    ]
    # Audio OK on source (preserved), but report it
    try:
        info = probe_video(path)
        if info.has_audio:
            results.append(CheckResult(
                "source_audio", True, "audio present", "preserved",
                "Source has audio track — preserved in sources/, stripped on conversion",
                severity="info",
            ))
        else:
            results.append(CheckResult(
                "source_audio", True, "no audio", "n/a",
                "Source has no audio track", severity="info",
            ))
    except VideoProbeError:
        pass
    return results


def check_loop_video(path: Path, expected_duration: float = RECOMMENDED_LOOP_DURATION) -> list[CheckResult]:
    """Run all checks expected of a loop playback copy."""
    return [
        check_duration(path, expected_duration),
        check_codec(path),
        check_has_no_audio(path),
        check_frame_count(path, expected_fps=24.0, expected_duration=expected_duration),
        check_loop_continuity(path),
    ]


def check_output_pack(output_dir: Path, display_info: DisplayInfo) -> list[CheckResult]:
    """Verify a fully converted pack output directory (intro + loop + still)."""
    results: list[CheckResult] = []

    intro = output_dir / INTRO_FILENAME
    loop  = output_dir / LOOP_FILENAME
    still = output_dir / STILL_FILENAME

    # intro.mp4
    if not intro.exists():
        results.append(CheckResult("intro_exists", False, None, "file", f"Missing {INTRO_FILENAME}"))
    else:
        results.extend([
            check_duration(intro, RECOMMENDED_INTRO_DURATION),
            check_resolution(intro, display_info.width, display_info.height),
            check_codec(intro),
            check_has_no_audio(intro),
            check_pix_fmt(intro),
        ])

    # loop.mp4
    if not loop.exists():
        results.append(CheckResult("loop_exists", False, None, "file", f"Missing {LOOP_FILENAME}"))
    else:
        results.extend(check_loop_video(loop, RECOMMENDED_LOOP_DURATION))
        if loop.exists():
            results.append(check_resolution(loop, display_info.width, display_info.height))

    # still.rgb565
    expected_still_size = display_info.width * display_info.height * 2
    if not still.exists():
        results.append(CheckResult("still_exists", False, None, "file", f"Missing {STILL_FILENAME}"))
    else:
        actual_size = still.stat().st_size
        size_ok = actual_size == expected_still_size
        results.append(CheckResult(
            name="still_size",
            passed=size_ok,
            actual=actual_size,
            expected=expected_still_size,
            message=(f"still.rgb565 is {actual_size:,} bytes "
                     f"({'correct' if size_ok else f'expected {expected_still_size:,}'})"),
            severity="error" if not size_ok else "info",
        ))

    return results
