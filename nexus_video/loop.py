"""Loop generation strategies: derive a seamless 5-second loop from an intro video."""

import logging
import subprocess
import tempfile
from enum import Enum
from pathlib import Path
from typing import Optional

from .config import RECOMMENDED_LOOP_DURATION
from .packs import probe_video

log = logging.getLogger(__name__)


class LoopStrategy(str, Enum):
    PALINDROME = "palindrome"   # forward + reversed segment; best general-purpose choice
    FREEZE     = "freeze"       # last frame held for the full duration
    CROSSFADE  = "crossfade"    # end blends back into start via xfade filter


class LoopError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Strategy implementations
# ---------------------------------------------------------------------------

def _run_ffmpeg(cmd: list[str], label: str, timeout: int = 120) -> None:
    log.debug("ffmpeg [%s]: %s", label, " ".join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise LoopError("ffmpeg not found — install ffmpeg") from exc
    except subprocess.TimeoutExpired as exc:
        raise LoopError(f"ffmpeg timed out generating loop ({label})") from exc
    if result.returncode != 0:
        raise LoopError(f"ffmpeg failed [{label}] (exit {result.returncode}):\n{result.stderr.strip()}")


def _h264_encode_args(crf: int = 18, threads: int = 2) -> list[str]:
    return ["-c:v", "libx264", "-profile:v", "high", "-preset", "slow",
            "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart"]


def make_palindrome_loop(
    src: Path,
    dst: Path,
    duration: float = RECOMMENDED_LOOP_DURATION,
    segment_start: Optional[float] = None,
    crf: int = 18,
    threads: int = 2,
) -> None:
    """Generate a seamless loop by playing a segment forward then in reverse.

    By construction the first and last frames are identical, giving a perfect
    visual loop point regardless of content.

    Args:
        src:            Source intro video (any resolution, with or without audio).
        dst:            Output loop file (silent, same container as other pack files).
        duration:       Total loop duration in seconds (forward + reverse = 2 × segment).
        segment_start:  Start of the segment within src (defaults to src_duration − segment_len).
        crf:            H.264 quality. 18 = visually lossless.
        threads:        ffmpeg thread limit (keep ≤ 2 on Pi).
    """
    if not src.exists():
        raise LoopError(f"Source not found: {src}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    segment_len = duration / 2.0

    # Default: take the last segment from the source
    if segment_start is None:
        try:
            info = probe_video(src)
            segment_start = max(0.0, info.duration - segment_len)
        except Exception as exc:
            raise LoopError(f"Cannot probe {src} to determine segment start: {exc}") from exc

    # ffmpeg filter: split → forward half + reversed half → concat
    filter_graph = (
        "[0:v]split[fwd][tmp];"
        "[tmp]reverse[rev];"
        "[fwd][rev]concat=n=2:v=1:a=0[out]"
    )
    cmd = [
        "ffmpeg", "-y", "-nostdin", "-v", "error",
        "-threads", str(threads),
        "-ss", str(segment_start), "-t", str(segment_len),
        "-i", str(src),
        "-filter_complex", filter_graph,
        "-map", "[out]",
        "-an",
    ] + _h264_encode_args(crf, threads) + [str(dst)]

    log.info("Generating palindrome loop from %s [%.2fs–%.2fs] → %s",
             src.name, segment_start, segment_start + segment_len, dst.name)
    _run_ffmpeg(cmd, "palindrome")
    log.info("Palindrome loop written: %s (%.1f KB)", dst, dst.stat().st_size / 1024)


def make_freeze_loop(
    src: Path,
    dst: Path,
    duration: float = RECOMMENDED_LOOP_DURATION,
    crf: int = 18,
    threads: int = 2,
) -> None:
    """Generate a loop by freezing the last frame of src for `duration` seconds.

    Produces a perfectly seamless loop (every frame is identical). Best for
    animations that end on a clean hold frame or a logo lockup.

    Uses a two-step pipeline: extract the last frame as PNG, then encode a
    looping video from that image. This is necessary because -loop 1 only
    works for image inputs in ffmpeg, not for video containers.
    """
    if not src.exists():
        raise LoopError(f"Source not found: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        frame_png = Path(tmpdir) / "last_frame.png"

        # Step 1: extract the last frame as a lossless PNG
        extract_cmd = [
            "ffmpeg", "-y", "-nostdin", "-v", "error",
            "-sseof", "-0.5",
            "-i", str(src),
            "-vframes", "1",
            str(frame_png),
        ]
        _run_ffmpeg(extract_cmd, "freeze-extract")

        if not frame_png.exists():
            raise LoopError(f"Frame extraction produced no output for {src}")

        # Step 2: loop the PNG for the requested duration
        loop_cmd = [
            "ffmpeg", "-y", "-nostdin", "-v", "error",
            "-threads", str(threads),
            "-loop", "1", "-t", str(duration),
            "-i", str(frame_png),
            "-an",
        ] + _h264_encode_args(crf, threads) + [str(dst)]

        log.info("Generating freeze loop from %s (last frame × %.1fs) → %s",
                 src.name, duration, dst.name)
        _run_ffmpeg(loop_cmd, "freeze-loop")

    log.info("Freeze loop written: %s (%.1f KB)", dst, dst.stat().st_size / 1024)


def make_crossfade_loop(
    src: Path,
    dst: Path,
    duration: float = RECOMMENDED_LOOP_DURATION,
    fade_seconds: float = 0.5,
    crf: int = 18,
    threads: int = 2,
) -> None:
    """Generate a loop where the end cross-fades into the start via xfade.

    Takes the last `duration` seconds of src and blends a `fade_seconds`
    transition at the loop point. Best for content with steady motion where a
    hard cut would be noticeable but neither freeze nor palindrome fit well.
    """
    if not src.exists():
        raise LoopError(f"Source not found: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)

    try:
        info = probe_video(src)
    except Exception as exc:
        raise LoopError(f"Cannot probe {src}: {exc}") from exc

    segment_start = max(0.0, info.duration - duration)

    # Trim to the loop segment, duplicate it, then xfade end-of-first → start-of-second
    # xfade offset = duration - fade_seconds (start the crossfade this many seconds in)
    xfade_offset = duration - fade_seconds
    filter_graph = (
        f"[0:v]split[a][b];"
        f"[a][b]xfade=transition=fade:duration={fade_seconds}:offset={xfade_offset}[out]"
    )
    cmd = [
        "ffmpeg", "-y", "-nostdin", "-v", "error",
        "-threads", str(threads),
        "-ss", str(segment_start), "-t", str(duration),
        "-i", str(src),
        "-filter_complex", filter_graph,
        "-map", "[out]",
        "-an",
        "-t", str(duration),
    ] + _h264_encode_args(crf, threads) + [str(dst)]

    log.info("Generating crossfade loop from %s [%.2fs–%.2fs] fade=%.1fs → %s",
             src.name, segment_start, segment_start + duration, fade_seconds, dst.name)
    _run_ffmpeg(cmd, "crossfade")
    log.info("Crossfade loop written: %s (%.1f KB)", dst, dst.stat().st_size / 1024)


# ---------------------------------------------------------------------------
# Dispatch helper
# ---------------------------------------------------------------------------

STRATEGY_FN = {
    LoopStrategy.PALINDROME: make_palindrome_loop,
    LoopStrategy.FREEZE:     make_freeze_loop,
    LoopStrategy.CROSSFADE:  make_crossfade_loop,
}


def generate_loop(
    src: Path,
    dst: Path,
    strategy: str = LoopStrategy.PALINDROME,
    duration: float = RECOMMENDED_LOOP_DURATION,
    **kwargs,
) -> None:
    """Generate a loop from *src* using the named strategy.

    Args:
        src:      Source intro video.
        dst:      Destination loop video (silent).
        strategy: One of "palindrome", "freeze", "crossfade".
        duration: Target loop duration in seconds.
        **kwargs: Passed through to the strategy function (e.g. segment_start, fade_seconds).
    """
    strat = LoopStrategy(strategy)
    fn = STRATEGY_FN[strat]
    fn(src=src, dst=dst, duration=duration, **kwargs)
