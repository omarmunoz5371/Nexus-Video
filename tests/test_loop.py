"""Tests for nexus_video.loop — loop generation strategies."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nexus_video.loop import (
    LoopError, LoopStrategy,
    generate_loop, make_crossfade_loop, make_freeze_loop, make_palindrome_loop,
)
from nexus_video.packs import probe_video
from tests.conftest import needs_ffmpeg, HAVE_FFMPEG


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def synthetic_intro(tmp_path: Path) -> Path:
    """1280×720 H.264 intro at 24fps for 3 seconds (short for fast test runs)."""
    if not HAVE_FFMPEG:
        pytest.skip("ffmpeg not available")
    p = tmp_path / "intro.mp4"
    cmd = [
        "ffmpeg", "-y", "-nostdin", "-v", "error",
        "-f", "lavfi", "-i", "testsrc=duration=3:size=1280x720:rate=24",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p),
    ]
    subprocess.run(cmd, capture_output=True, check=True, timeout=30)
    return p


def _mock_probe_duration(dur: float):
    from nexus_video.packs import VideoInfo
    mock_info = VideoInfo(duration=dur, width=1280, height=720, codec="h264",
                          has_audio=False, raw={"streams": [{"nb_frames": str(int(dur*24)),
                                                               "r_frame_rate": "24/1"}]})
    return patch("nexus_video.loop.probe_video", return_value=mock_info)


def _mock_ffmpeg_ok():
    def side_effect(cmd, **kw):
        # Create a tiny output file so callers can stat() it
        dst = Path(cmd[-1])
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"\x00" * 100)
        return MagicMock(returncode=0, stderr="", stdout="")
    return patch("nexus_video.loop.subprocess.run", side_effect=side_effect)


# ---------------------------------------------------------------------------
# LoopStrategy enum
# ---------------------------------------------------------------------------

class TestLoopStrategy:
    def test_valid_strategy_names(self):
        assert LoopStrategy("palindrome") == LoopStrategy.PALINDROME
        assert LoopStrategy("freeze")     == LoopStrategy.FREEZE
        assert LoopStrategy("crossfade")  == LoopStrategy.CROSSFADE

    def test_invalid_strategy_raises(self):
        with pytest.raises(ValueError):
            LoopStrategy("boomerang")


# ---------------------------------------------------------------------------
# generate_loop dispatch
# ---------------------------------------------------------------------------

class TestGenerateLoop:
    def test_palindrome_dispatches_correctly(self, tmp_path):
        src = tmp_path / "src.mp4"
        src.write_bytes(b"\x00")
        dst = tmp_path / "out.mp4"
        with _mock_probe_duration(3.0), _mock_ffmpeg_ok():
            generate_loop(src, dst, strategy="palindrome", duration=2.0)
        assert dst.exists()

    def test_freeze_dispatches_correctly(self, tmp_path):
        src = tmp_path / "src.mp4"
        src.write_bytes(b"\x00")
        dst = tmp_path / "out.mp4"
        with _mock_ffmpeg_ok():
            generate_loop(src, dst, strategy="freeze", duration=5.0)
        assert dst.exists()

    def test_crossfade_dispatches_correctly(self, tmp_path):
        src = tmp_path / "src.mp4"
        src.write_bytes(b"\x00")
        dst = tmp_path / "out.mp4"
        with _mock_probe_duration(3.0), _mock_ffmpeg_ok():
            generate_loop(src, dst, strategy="crossfade", duration=2.0)
        assert dst.exists()

    def test_raises_for_unknown_strategy(self, tmp_path):
        src = tmp_path / "src.mp4"
        src.write_bytes(b"\x00")
        with pytest.raises(ValueError):
            generate_loop(src, tmp_path / "out.mp4", strategy="unknown")


# ---------------------------------------------------------------------------
# make_palindrome_loop
# ---------------------------------------------------------------------------

class TestMakePalindromeLoop:
    def test_raises_when_source_missing(self, tmp_path):
        with pytest.raises(LoopError, match="Source not found"):
            make_palindrome_loop(tmp_path / "missing.mp4", tmp_path / "out.mp4")

    def test_raises_when_ffmpeg_not_found(self, tmp_path):
        src = tmp_path / "src.mp4"
        src.write_bytes(b"\x00")
        with _mock_probe_duration(3.0), \
             patch("nexus_video.loop.subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(LoopError, match="ffmpeg not found"):
                make_palindrome_loop(src, tmp_path / "out.mp4", duration=2.0)

    def test_raises_when_ffmpeg_fails(self, tmp_path):
        src = tmp_path / "src.mp4"
        src.write_bytes(b"\x00")
        fail = MagicMock(returncode=1, stderr="Conversion error", stdout="")
        with _mock_probe_duration(3.0), \
             patch("nexus_video.loop.subprocess.run", return_value=fail):
            with pytest.raises(LoopError, match="ffmpeg failed"):
                make_palindrome_loop(src, tmp_path / "out.mp4", duration=2.0)

    def test_raises_on_timeout(self, tmp_path):
        src = tmp_path / "src.mp4"
        src.write_bytes(b"\x00")
        with _mock_probe_duration(3.0), \
             patch("nexus_video.loop.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("ffmpeg", 120)):
            with pytest.raises(LoopError, match="timed out"):
                make_palindrome_loop(src, tmp_path / "out.mp4", duration=2.0)

    def test_ffmpeg_command_includes_reverse_filter(self, tmp_path):
        src = tmp_path / "src.mp4"
        src.write_bytes(b"\x00")
        dst = tmp_path / "out.mp4"
        captured = []

        def capture(cmd, **kw):
            captured.extend(cmd)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(b"\x00")
            return MagicMock(returncode=0, stderr="")

        with _mock_probe_duration(3.0), \
             patch("nexus_video.loop.subprocess.run", side_effect=capture):
            make_palindrome_loop(src, dst, duration=2.0, segment_start=0.5)

        cmd_str = " ".join(captured)
        assert "reverse" in cmd_str
        assert "concat" in cmd_str
        assert "-an" in captured

    def test_segment_start_defaults_to_last_segment(self, tmp_path):
        src = tmp_path / "src.mp4"
        src.write_bytes(b"\x00")
        captured = []

        def capture(cmd, **kw):
            captured.extend(cmd)
            Path(cmd[-1]).write_bytes(b"\x00")
            return MagicMock(returncode=0, stderr="")

        with _mock_probe_duration(10.0), \
             patch("nexus_video.loop.subprocess.run", side_effect=capture):
            make_palindrome_loop(src, tmp_path / "out.mp4", duration=5.0)

        # segment_start should be 10.0 - 2.5 = 7.5
        ss_idx = captured.index("-ss")
        assert float(captured[ss_idx + 1]) == pytest.approx(7.5)

    def test_output_dir_created_if_missing(self, tmp_path):
        src = tmp_path / "src.mp4"
        src.write_bytes(b"\x00")
        dst = tmp_path / "deep" / "nested" / "out.mp4"
        with _mock_probe_duration(3.0), _mock_ffmpeg_ok():
            make_palindrome_loop(src, dst, duration=2.0, segment_start=0.0)
        assert dst.parent.exists()

    @needs_ffmpeg
    def test_real_palindrome_produces_correct_duration(self, synthetic_intro, tmp_path):
        dst = tmp_path / "loop.mp4"
        make_palindrome_loop(synthetic_intro, dst, duration=2.0)
        info = probe_video(dst)
        assert abs(info.duration - 2.0) < 0.1

    @needs_ffmpeg
    def test_real_palindrome_has_no_audio(self, synthetic_intro, tmp_path):
        dst = tmp_path / "loop.mp4"
        make_palindrome_loop(synthetic_intro, dst, duration=2.0)
        info = probe_video(dst)
        assert not info.has_audio

    @needs_ffmpeg
    def test_real_palindrome_correct_resolution(self, synthetic_intro, tmp_path):
        dst = tmp_path / "loop.mp4"
        make_palindrome_loop(synthetic_intro, dst, duration=2.0)
        info = probe_video(dst)
        assert info.width == 1280
        assert info.height == 720


# ---------------------------------------------------------------------------
# make_freeze_loop
# ---------------------------------------------------------------------------

class TestMakeFreezeLoop:
    def test_raises_when_source_missing(self, tmp_path):
        with pytest.raises(LoopError, match="Source not found"):
            make_freeze_loop(tmp_path / "missing.mp4", tmp_path / "out.mp4")

    def test_ffmpeg_command_uses_loop_flag(self, tmp_path):
        src = tmp_path / "src.mp4"
        src.write_bytes(b"\x00")
        dst = tmp_path / "out.mp4"
        all_cmds: list[list[str]] = []

        def capture(cmd, **kw):
            all_cmds.append(list(cmd))
            # For the extraction step, create the PNG; for the loop step, create the mp4
            out = Path(cmd[-1])
            out.write_bytes(b"\x00\x01")
            return MagicMock(returncode=0, stderr="")

        with patch("nexus_video.loop.subprocess.run", side_effect=capture):
            make_freeze_loop(src, dst, duration=5.0)

        assert len(all_cmds) == 2, "Expected two ffmpeg calls: extract then loop"
        extract_cmd = " ".join(all_cmds[0])
        loop_cmd    = " ".join(all_cmds[1])
        assert "-sseof" in extract_cmd          # extraction step
        assert "-loop" in loop_cmd              # loop step
        assert "-an" in loop_cmd                # audio stripped

    @needs_ffmpeg
    def test_real_freeze_produces_correct_duration(self, synthetic_intro, tmp_path):
        dst = tmp_path / "freeze.mp4"
        make_freeze_loop(synthetic_intro, dst, duration=5.0)
        info = probe_video(dst)
        assert abs(info.duration - 5.0) < 0.2

    @needs_ffmpeg
    def test_real_freeze_has_no_audio(self, synthetic_intro, tmp_path):
        dst = tmp_path / "freeze.mp4"
        make_freeze_loop(synthetic_intro, dst, duration=5.0)
        info = probe_video(dst)
        assert not info.has_audio


# ---------------------------------------------------------------------------
# make_crossfade_loop
# ---------------------------------------------------------------------------

class TestMakeCrossfadeLoop:
    def test_raises_when_source_missing(self, tmp_path):
        with pytest.raises(LoopError, match="Source not found"):
            make_crossfade_loop(tmp_path / "missing.mp4", tmp_path / "out.mp4")

    def test_ffmpeg_command_uses_xfade(self, tmp_path):
        src = tmp_path / "src.mp4"
        src.write_bytes(b"\x00")
        captured = []

        def capture(cmd, **kw):
            captured.extend(cmd)
            Path(cmd[-1]).write_bytes(b"\x00")
            return MagicMock(returncode=0, stderr="")

        with _mock_probe_duration(5.0), \
             patch("nexus_video.loop.subprocess.run", side_effect=capture):
            make_crossfade_loop(src, tmp_path / "out.mp4", duration=5.0)

        cmd_str = " ".join(captured)
        assert "xfade" in cmd_str
        assert "-an" in captured
