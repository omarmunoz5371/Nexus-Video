"""Tests for nexus_video.check — automated quality checks."""

import math
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nexus_video.check import (
    CheckResult,
    check_codec, check_duration, check_frame_count, check_has_no_audio,
    check_loop_continuity, check_output_pack, check_pix_fmt, check_resolution,
    check_source_video, check_loop_video, _psnr,
)
from nexus_video.config import INTRO_FILENAME, LOOP_FILENAME, STILL_FILENAME
from nexus_video.detect import DisplayInfo
from nexus_video.packs import VideoInfo
from tests.conftest import needs_ffmpeg, HAVE_FFMPEG


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def display_800x480() -> DisplayInfo:
    return DisplayInfo(width=800, height=480, bpp=16, stride=1600)


def _mock_probe(duration=10.0, width=1280, height=720, codec="h264",
                has_audio=False, nb_frames="240", r_frame_rate="24/1"):
    info = VideoInfo(
        duration=duration, width=width, height=height, codec=codec, has_audio=has_audio,
        raw={
            "streams": [{
                "codec_type": "video", "codec_name": codec,
                "width": width, "height": height,
                "r_frame_rate": r_frame_rate, "nb_frames": nb_frames,
                "pix_fmt": "yuv420p",
            }],
            "format": {"duration": str(duration)},
        }
    )
    return patch("nexus_video.check.probe_video", return_value=info)


def _mock_probe_fail(msg="ffprobe failed"):
    from nexus_video.packs import VideoProbeError
    return patch("nexus_video.check.probe_video", side_effect=VideoProbeError(msg))


# ---------------------------------------------------------------------------
# _psnr
# ---------------------------------------------------------------------------

class TestPsnr:
    def test_identical_bytes_returns_inf(self):
        data = bytes(range(256)) * 10
        assert _psnr(data, data) == float("inf")

    def test_different_bytes_returns_finite(self):
        a = bytes([0] * 100)
        b = bytes([10] * 100)
        psnr = _psnr(a, b)
        assert math.isfinite(psnr)
        assert psnr > 0

    def test_raises_on_size_mismatch(self):
        with pytest.raises(ValueError, match="size mismatch"):
            _psnr(bytes(10), bytes(20))

    def test_known_psnr_value(self):
        # MSE = 100, PSNR = 10 * log10(255^2 / 100) ≈ 28.13 dB
        a = bytes([0] * 100)
        b = bytes([10] * 100)   # MSE = 100
        psnr = _psnr(a, b)
        assert abs(psnr - 28.13) < 0.1


# ---------------------------------------------------------------------------
# check_codec
# ---------------------------------------------------------------------------

class TestCheckCodec:
    def test_matching_codec_passes(self, tmp_path):
        p = tmp_path / "v.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe(codec="h264"):
            r = check_codec(p, expected="h264")
        assert r.passed

    def test_wrong_codec_fails(self, tmp_path):
        p = tmp_path / "v.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe(codec="hevc"):
            r = check_codec(p, expected="h264")
        assert not r.passed

    def test_probe_failure_gives_failed_result(self, tmp_path):
        p = tmp_path / "v.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe_fail():
            r = check_codec(p)
        assert not r.passed

    def test_case_insensitive(self, tmp_path):
        p = tmp_path / "v.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe(codec="H264"):
            r = check_codec(p, expected="h264")
        assert r.passed


# ---------------------------------------------------------------------------
# check_resolution
# ---------------------------------------------------------------------------

class TestCheckResolution:
    def test_matching_resolution_passes(self, tmp_path):
        p = tmp_path / "v.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe(width=800, height=480):
            r = check_resolution(p, 800, 480)
        assert r.passed

    def test_wrong_width_fails(self, tmp_path):
        p = tmp_path / "v.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe(width=1280, height=480):
            r = check_resolution(p, 800, 480)
        assert not r.passed

    def test_wrong_height_fails(self, tmp_path):
        p = tmp_path / "v.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe(width=800, height=720):
            r = check_resolution(p, 800, 480)
        assert not r.passed


# ---------------------------------------------------------------------------
# check_duration
# ---------------------------------------------------------------------------

class TestCheckDuration:
    def test_exact_duration_passes(self, tmp_path):
        p = tmp_path / "v.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe(duration=10.0):
            r = check_duration(p, expected=10.0, tolerance=0.5)
        assert r.passed

    def test_within_tolerance_passes(self, tmp_path):
        p = tmp_path / "v.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe(duration=10.4):
            r = check_duration(p, expected=10.0, tolerance=0.5)
        assert r.passed

    def test_outside_tolerance_fails(self, tmp_path):
        p = tmp_path / "v.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe(duration=15.0):
            r = check_duration(p, expected=10.0, tolerance=0.5)
        assert not r.passed
        assert r.severity == "warning"  # duration mismatch is a warning, not error

    def test_actual_value_in_result(self, tmp_path):
        p = tmp_path / "v.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe(duration=9.8):
            r = check_duration(p, expected=10.0, tolerance=0.5)
        assert r.actual == 9.8


# ---------------------------------------------------------------------------
# check_frame_count
# ---------------------------------------------------------------------------

class TestCheckFrameCount:
    def test_correct_frame_count_passes(self, tmp_path):
        p = tmp_path / "v.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe(duration=10.0, nb_frames="240"):
            r = check_frame_count(p, expected_fps=24.0, expected_duration=10.0)
        assert r.passed

    def test_within_tolerance_passes(self, tmp_path):
        p = tmp_path / "v.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe(duration=10.0, nb_frames="239"):
            r = check_frame_count(p, expected_fps=24.0, expected_duration=10.0, tolerance=2)
        assert r.passed

    def test_outside_tolerance_fails(self, tmp_path):
        p = tmp_path / "v.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe(duration=10.0, nb_frames="200"):
            r = check_frame_count(p, expected_fps=24.0, expected_duration=10.0, tolerance=2)
        assert not r.passed

    def test_uses_probed_duration_when_expected_not_given(self, tmp_path):
        p = tmp_path / "v.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe(duration=5.0, nb_frames="120"):
            r = check_frame_count(p, expected_fps=24.0)
        assert r.passed

    def test_falls_back_to_r_frame_rate_when_nb_frames_missing(self, tmp_path):
        p = tmp_path / "v.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe(duration=5.0, nb_frames="", r_frame_rate="24/1"):
            r = check_frame_count(p, expected_fps=24.0, expected_duration=5.0)
        assert r.passed


# ---------------------------------------------------------------------------
# check_has_no_audio
# ---------------------------------------------------------------------------

class TestCheckHasNoAudio:
    def test_no_audio_passes(self, tmp_path):
        p = tmp_path / "v.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe(has_audio=False):
            r = check_has_no_audio(p)
        assert r.passed

    def test_audio_present_fails_with_warning(self, tmp_path):
        p = tmp_path / "v.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe(has_audio=True):
            r = check_has_no_audio(p)
        assert not r.passed
        assert r.severity == "warning"


# ---------------------------------------------------------------------------
# check_pix_fmt
# ---------------------------------------------------------------------------

class TestCheckPixFmt:
    def test_correct_pix_fmt_passes(self, tmp_path):
        p = tmp_path / "v.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe():
            r = check_pix_fmt(p, expected="yuv420p")
        assert r.passed

    def test_wrong_pix_fmt_fails(self, tmp_path):
        p = tmp_path / "v.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe():
            # Mock returns yuv420p; check for yuv444p
            r = check_pix_fmt(p, expected="yuv444p")
        assert not r.passed


# ---------------------------------------------------------------------------
# check_loop_continuity
# ---------------------------------------------------------------------------

class TestCheckLoopContinuity:
    def test_missing_file_gives_failed_result(self, tmp_path):
        r = check_loop_continuity(tmp_path / "missing.mp4")
        assert not r.passed
        assert "not found" in r.message

    def test_identical_frames_passes(self, tmp_path):
        """Identical first and last frames → infinite PSNR → PASS."""
        p = tmp_path / "loop.mp4"
        p.write_bytes(b"\x00")
        pixel_data = bytes(range(256)) * 300  # arbitrary RGB24 data

        with patch("nexus_video.check._extract_frame_rgb24", return_value=pixel_data):
            r = check_loop_continuity(p, psnr_threshold_seamless=35.0)

        assert r.passed
        assert "∞" in r.message

    def test_different_frames_at_psnr_below_seamless_threshold(self, tmp_path):
        p = tmp_path / "loop.mp4"
        p.write_bytes(b"\x00")

        call_count = [0]
        def fake_extract(*args, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return bytes([0] * 1000)   # first frame: black
            return bytes([50] * 1000)      # last frame: grey → PSNR ≈ 14 dB

        with patch("nexus_video.check._extract_frame_rgb24", side_effect=fake_extract):
            r = check_loop_continuity(p, psnr_threshold_seamless=35.0, psnr_threshold_acceptable=25.0)

        assert not r.passed
        assert r.severity == "error"

    def test_good_psnr_passes(self, tmp_path):
        p = tmp_path / "loop.mp4"
        p.write_bytes(b"\x00")
        # Create frames with tiny difference → PSNR > 35 dB
        base = bytes(range(256)) * 400  # 102400 bytes
        slightly_different = bytes([(b + 1) % 256 for b in base[:50]] + list(base[50:]))
        frames = [base, slightly_different]

        def fake_extract(*args, **kw):
            return frames.pop(0)

        with patch("nexus_video.check._extract_frame_rgb24", side_effect=fake_extract):
            r = check_loop_continuity(p, psnr_threshold_seamless=35.0)

        assert r.passed

    def test_extraction_failure_gives_failed_result(self, tmp_path):
        p = tmp_path / "loop.mp4"
        p.write_bytes(b"\x00")

        with patch("nexus_video.check._extract_frame_rgb24", side_effect=RuntimeError("decode failed")):
            r = check_loop_continuity(p)

        assert not r.passed
        assert "extraction failed" in r.message.lower()

    @needs_ffmpeg
    def test_real_palindrome_loop_continuity(self, tmp_path):
        """Integration: generate a real palindrome loop and verify continuity check passes."""
        intro = tmp_path / "intro.mp4"
        cmd = [
            "ffmpeg", "-y", "-nostdin", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=24",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(intro),
        ]
        subprocess.run(cmd, capture_output=True, check=True)

        from nexus_video.loop import make_palindrome_loop
        loop = tmp_path / "loop.mp4"
        make_palindrome_loop(intro, loop, duration=2.0)

        r = check_loop_continuity(loop)
        assert r.passed, f"Expected PASS but got: {r.message}"


# ---------------------------------------------------------------------------
# check_source_video
# ---------------------------------------------------------------------------

class TestCheckSourceVideo:
    def test_valid_source_all_pass(self, tmp_path):
        p = tmp_path / "intro.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe(duration=10.0, codec="h264", nb_frames="240"):
            results = check_source_video(p, expected_duration=10.0)
        passing = [r for r in results if not r.passed and r.severity == "error"]
        assert passing == [], f"Unexpected errors: {passing}"

    def test_wrong_duration_gives_warning(self, tmp_path):
        p = tmp_path / "intro.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe(duration=30.0, codec="h264", nb_frames="720"):
            results = check_source_video(p, expected_duration=10.0)
        dur_result = next((r for r in results if r.name == "duration"), None)
        assert dur_result is not None
        assert not dur_result.passed
        assert dur_result.severity == "warning"


# ---------------------------------------------------------------------------
# check_output_pack
# ---------------------------------------------------------------------------

class TestCheckOutputPack:
    def _write_valid_output(self, out_dir: Path, display: DisplayInfo) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / INTRO_FILENAME).write_bytes(b"\x00\x01")
        (out_dir / LOOP_FILENAME).write_bytes(b"\x00\x01")
        still_size = display.width * display.height * 2
        (out_dir / STILL_FILENAME).write_bytes(bytes(still_size))

    def test_missing_intro_gives_error(self, tmp_path, display_800x480):
        self._write_valid_output(tmp_path, display_800x480)
        (tmp_path / INTRO_FILENAME).unlink()
        with _mock_probe(width=800, height=480, duration=5.0):
            results = check_output_pack(tmp_path, display_800x480)
        errors = [r for r in results if not r.passed and r.severity == "error"]
        assert any("intro" in r.name.lower() for r in errors)

    def test_missing_loop_gives_error(self, tmp_path, display_800x480):
        self._write_valid_output(tmp_path, display_800x480)
        (tmp_path / LOOP_FILENAME).unlink()
        with _mock_probe(width=800, height=480, duration=5.0):
            results = check_output_pack(tmp_path, display_800x480)
        errors = [r for r in results if not r.passed]
        assert any("loop" in r.name.lower() for r in errors)

    def test_wrong_still_size_gives_error(self, tmp_path, display_800x480):
        self._write_valid_output(tmp_path, display_800x480)
        (tmp_path / STILL_FILENAME).write_bytes(bytes(42))  # wrong size
        with _mock_probe(width=800, height=480, duration=10.0):
            results = check_output_pack(tmp_path, display_800x480)
        still_result = next((r for r in results if r.name == "still_size"), None)
        assert still_result is not None
        assert not still_result.passed

    def test_correct_still_size_passes(self, tmp_path, display_800x480):
        self._write_valid_output(tmp_path, display_800x480)
        with _mock_probe(width=800, height=480, duration=10.0, has_audio=False):
            results = check_output_pack(tmp_path, display_800x480)
        still_result = next((r for r in results if r.name == "still_size"), None)
        assert still_result is not None
        assert still_result.passed

    def test_still_size_validation_uses_display_dimensions(self, tmp_path):
        display = DisplayInfo(width=1024, height=600, bpp=16, stride=2048)
        out = tmp_path / "out"
        out.mkdir()
        (out / INTRO_FILENAME).write_bytes(b"\x00")
        (out / LOOP_FILENAME).write_bytes(b"\x00")
        expected = 1024 * 600 * 2
        (out / STILL_FILENAME).write_bytes(bytes(expected))
        with _mock_probe(width=1024, height=600, duration=10.0):
            results = check_output_pack(out, display)
        still_result = next((r for r in results if r.name == "still_size"), None)
        assert still_result.passed

    @needs_ffmpeg
    def test_pipeline_verification_1280x720_to_800x480(self, tmp_path):
        """Integration: verify full pipeline converts 1280x720 H.264 → 800x480 and passes all checks."""
        from nexus_video.convert import convert_video, generate_still

        src = tmp_path / "source.mp4"
        cmd = [
            "ffmpeg", "-y", "-nostdin", "-v", "error",
            "-f", "lavfi",
            "-i", "testsrc=duration=1:size=1280x720:rate=24",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src),
        ]
        subprocess.run(cmd, capture_output=True, check=True, timeout=30)

        display = DisplayInfo(width=800, height=480, bpp=16, stride=1600)
        out = tmp_path / "out"
        out.mkdir()

        convert_video(src, out / INTRO_FILENAME, display, scale_mode="fit")
        convert_video(src, out / LOOP_FILENAME,  display, scale_mode="fit")
        generate_still(out, display, source=out / INTRO_FILENAME)

        results = check_output_pack(out, display)
        hard_errors = [r for r in results if not r.passed and r.severity == "error"
                       and r.name not in ("duration", "frame_count", "loop_continuity")]
        assert hard_errors == [], f"Unexpected hard errors: {hard_errors}"
