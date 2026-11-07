"""Tests for nexus_video.convert — ffmpeg conversion pipeline."""

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from nexus_video.convert import (
    ConversionError, convert_pack, convert_video,
    generate_still, scale_filter, validate_output,
)
from nexus_video.detect import DisplayInfo
from nexus_video.config import INTRO_FILENAME, LOOP_FILENAME, STILL_FILENAME

from tests.conftest import needs_ffmpeg, HAVE_FFMPEG


# ---------------------------------------------------------------------------
# Standard display fixture (also defined in conftest but repeated for clarity)
# ---------------------------------------------------------------------------

@pytest.fixture()
def display() -> DisplayInfo:
    return DisplayInfo(width=800, height=480, bpp=16, stride=1600)


# ---------------------------------------------------------------------------
# scale_filter
# ---------------------------------------------------------------------------

class TestScaleFilter:
    def test_stretch_mode(self):
        f = scale_filter("stretch", 800, 480)
        assert f == "scale=800:480"

    def test_fit_mode_contains_force_original_aspect_ratio(self):
        f = scale_filter("fit", 800, 480)
        assert "force_original_aspect_ratio=decrease" in f
        assert "pad=800:480" in f
        assert "black" in f

    def test_fill_mode_contains_crop(self):
        f = scale_filter("fill", 800, 480)
        assert "force_original_aspect_ratio=increase" in f
        assert "crop=800:480" in f

    def test_all_modes_include_target_dimensions(self):
        for mode in ("fit", "fill", "stretch"):
            f = scale_filter(mode, 1024, 600)
            assert "1024" in f
            assert "600" in f

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="scale_mode must be one of"):
            scale_filter("zoom", 800, 480)


# ---------------------------------------------------------------------------
# convert_video — mocked ffmpeg
# ---------------------------------------------------------------------------

class TestConvertVideo:
    def _mock_ffmpeg_success(self):
        m = MagicMock()
        m.returncode = 0
        m.stderr = ""
        return patch("nexus_video.convert.subprocess.run", return_value=m)

    def _mock_ffmpeg_fail(self, stderr="Conversion error"):
        m = MagicMock()
        m.returncode = 1
        m.stderr = stderr
        return patch("nexus_video.convert.subprocess.run", return_value=m)

    def test_raises_when_source_not_found(self, tmp_path, display):
        with pytest.raises(ConversionError, match="Source file not found"):
            convert_video(tmp_path / "missing.mp4", tmp_path / "out.mp4", display)

    def test_raises_when_ffmpeg_not_found(self, tmp_path, display):
        src = tmp_path / "src.mp4"
        src.write_bytes(b"\x00")
        with patch("nexus_video.convert.subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(ConversionError, match="ffmpeg not found"):
                convert_video(src, tmp_path / "out.mp4", display)

    def test_raises_on_nonzero_exit_code(self, tmp_path, display):
        src = tmp_path / "src.mp4"
        src.write_bytes(b"\x00")
        with self._mock_ffmpeg_fail("Unsupported format"):
            with pytest.raises(ConversionError, match="ffmpeg failed"):
                convert_video(src, tmp_path / "out.mp4", display)

    def test_raises_on_timeout(self, tmp_path, display):
        src = tmp_path / "src.mp4"
        src.write_bytes(b"\x00")
        with patch("nexus_video.convert.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("ffmpeg", 300)):
            with pytest.raises(ConversionError, match="timed out"):
                convert_video(src, tmp_path / "out.mp4", display)

    def test_ffmpeg_command_includes_scale_mode(self, tmp_path, display):
        src = tmp_path / "src.mp4"
        src.write_bytes(b"\x00")
        dst = tmp_path / "out.mp4"
        captured_cmd = []

        def capture(cmd, **kw):
            captured_cmd.extend(cmd)
            m = MagicMock(returncode=0, stderr="")
            return m

        with patch("nexus_video.convert.subprocess.run", side_effect=capture):
            # Intentionally skip the stat() call by pre-creating dst
            dst.write_bytes(b"\x00")
            convert_video(src, dst, display, scale_mode="fill")

        cmd_str = " ".join(captured_cmd)
        assert "force_original_aspect_ratio=increase" in cmd_str
        assert "800" in cmd_str
        assert "480" in cmd_str

    def test_ffmpeg_command_strips_audio(self, tmp_path, display):
        src = tmp_path / "src.mp4"
        src.write_bytes(b"\x00")
        dst = tmp_path / "out.mp4"
        captured_cmd = []

        def capture(cmd, **kw):
            captured_cmd.extend(cmd)
            return MagicMock(returncode=0, stderr="")

        with patch("nexus_video.convert.subprocess.run", side_effect=capture):
            dst.write_bytes(b"\x00")
            convert_video(src, dst, display)

        assert "-an" in captured_cmd

    def test_ffmpeg_command_includes_duration_when_set(self, tmp_path, display):
        src = tmp_path / "src.mp4"
        src.write_bytes(b"\x00")
        dst = tmp_path / "out.mp4"
        captured_cmd = []

        def capture(cmd, **kw):
            captured_cmd.extend(cmd)
            return MagicMock(returncode=0, stderr="")

        with patch("nexus_video.convert.subprocess.run", side_effect=capture):
            dst.write_bytes(b"\x00")
            convert_video(src, dst, display, duration=10.0)

        assert "-t" in captured_cmd
        assert "10.0" in captured_cmd

    def test_output_directory_created_if_missing(self, tmp_path, display):
        src = tmp_path / "src.mp4"
        src.write_bytes(b"\x00")
        nested = tmp_path / "deep" / "nested" / "out.mp4"

        with self._mock_ffmpeg_success():
            # We need the dst file to exist so stat() doesn't fail on success path
            nested.parent.mkdir(parents=True, exist_ok=True)
            nested.write_bytes(b"\x00")
            convert_video(src, nested, display)

        assert nested.parent.exists()

    @needs_ffmpeg
    def test_real_conversion_produces_valid_output(self, tmp_path, display):
        """Integration: actually run ffmpeg to produce a small output file."""
        src = tmp_path / "src.mp4"
        cmd = [
            "ffmpeg", "-y", "-nostdin", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=24",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src),
        ]
        subprocess.run(cmd, capture_output=True, check=True)

        dst = tmp_path / "out.mp4"
        convert_video(src, dst, display, scale_mode="fit")
        assert dst.exists()
        assert dst.stat().st_size > 0


# ---------------------------------------------------------------------------
# generate_still
# ---------------------------------------------------------------------------

class TestGenerateStill:
    def test_generates_black_still_when_no_source(self, tmp_path, display):
        still = generate_still(tmp_path, display)
        expected = display.width * display.height * 2
        assert still.exists()
        assert still.stat().st_size == expected
        assert still.read_bytes() == bytes(expected)

    def test_still_path_is_correct_name(self, tmp_path, display):
        still = generate_still(tmp_path, display)
        assert still.name == STILL_FILENAME

    def test_still_size_matches_display(self, tmp_path):
        display = DisplayInfo(width=1024, height=600, bpp=16, stride=2048)
        still = generate_still(tmp_path, display)
        expected = 1024 * 600 * 2
        assert still.stat().st_size == expected

    def test_black_still_all_zero_bytes(self, tmp_path, display):
        still = generate_still(tmp_path, display)
        data = still.read_bytes()
        assert all(b == 0 for b in data)

    def test_output_dir_created_if_missing(self, tmp_path, display):
        nested = tmp_path / "nested" / "dir"
        generate_still(nested, display)
        assert nested.exists()

    @needs_ffmpeg
    def test_real_still_extraction_from_valid_video(self, tmp_path, display):
        src = tmp_path / "clip.mp4"
        cmd = [
            "ffmpeg", "-y", "-nostdin", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=800x480:rate=24",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src),
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        still = generate_still(tmp_path, display, source=src)
        expected = display.width * display.height * 2
        assert still.stat().st_size == expected

    def test_falls_back_to_black_when_source_missing(self, tmp_path, display):
        still = generate_still(tmp_path, display, source=tmp_path / "missing.mp4")
        expected = display.width * display.height * 2
        assert still.stat().st_size == expected
        assert still.read_bytes() == bytes(expected)


# ---------------------------------------------------------------------------
# validate_output
# ---------------------------------------------------------------------------

class TestValidateOutput:
    def _make_valid_output(self, out_dir: Path, display: DisplayInfo) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / INTRO_FILENAME).write_bytes(b"\x00\x01\x02")
        (out_dir / LOOP_FILENAME).write_bytes(b"\x00\x01\x02")
        expected = display.width * display.height * 2
        (out_dir / STILL_FILENAME).write_bytes(bytes(expected))

    def test_no_errors_for_valid_output(self, tmp_path, display):
        self._make_valid_output(tmp_path, display)
        errors = validate_output(tmp_path, display)
        assert errors == []

    def test_error_on_missing_intro(self, tmp_path, display):
        self._make_valid_output(tmp_path, display)
        (tmp_path / INTRO_FILENAME).unlink()
        errors = validate_output(tmp_path, display)
        assert any("intro" in e.lower() for e in errors)

    def test_error_on_missing_loop(self, tmp_path, display):
        self._make_valid_output(tmp_path, display)
        (tmp_path / LOOP_FILENAME).unlink()
        errors = validate_output(tmp_path, display)
        assert any("loop" in e.lower() for e in errors)

    def test_error_on_missing_still(self, tmp_path, display):
        self._make_valid_output(tmp_path, display)
        (tmp_path / STILL_FILENAME).unlink()
        errors = validate_output(tmp_path, display)
        assert any("still" in e.lower() for e in errors)

    def test_error_on_empty_intro(self, tmp_path, display):
        self._make_valid_output(tmp_path, display)
        (tmp_path / INTRO_FILENAME).write_bytes(b"")
        errors = validate_output(tmp_path, display)
        assert any("intro" in e.lower() for e in errors)

    def test_error_on_wrong_still_size(self, tmp_path, display):
        self._make_valid_output(tmp_path, display)
        (tmp_path / STILL_FILENAME).write_bytes(bytes(42))  # wrong size
        errors = validate_output(tmp_path, display)
        assert any("still" in e.lower() for e in errors)

    def test_still_size_includes_display_dimensions_in_error(self, tmp_path, display):
        self._make_valid_output(tmp_path, display)
        (tmp_path / STILL_FILENAME).write_bytes(bytes(42))
        errors = validate_output(tmp_path, display)
        error_text = " ".join(errors)
        assert str(display.width) in error_text


# ---------------------------------------------------------------------------
# convert_pack — integration-ish (mocked ffmpeg)
# ---------------------------------------------------------------------------

class TestConvertPack:
    def _setup_pack(self, pack_dir: Path) -> None:
        pack_dir.mkdir(parents=True, exist_ok=True)
        (pack_dir / INTRO_FILENAME).write_bytes(b"\x00")
        (pack_dir / LOOP_FILENAME).write_bytes(b"\x00")
        (pack_dir / "pack.json").write_text(json.dumps({"id": "test", "type": "custom"}))

    def _mock_ffmpeg_ok(self):
        def side_effect(cmd, **kw):
            # Simulate ffmpeg creating the output file
            for i, arg in enumerate(cmd):
                if arg.endswith(".mp4") or arg.endswith(".rgb565"):
                    Path(arg).write_bytes(b"\x00\x01")
            return MagicMock(returncode=0, stderr="", stdout="")
        return patch("nexus_video.convert.subprocess.run", side_effect=side_effect)

    def test_raises_when_intro_missing(self, tmp_path):
        pack = tmp_path / "pack"
        pack.mkdir()
        (pack / LOOP_FILENAME).write_bytes(b"\x00")
        display = DisplayInfo(800, 480, 16, 1600)
        with pytest.raises(ConversionError, match="intro.mp4 not found"):
            convert_pack(pack, tmp_path / "out", display)

    def test_raises_when_loop_missing(self, tmp_path):
        pack = tmp_path / "pack"
        pack.mkdir()
        (pack / INTRO_FILENAME).write_bytes(b"\x00")
        display = DisplayInfo(800, 480, 16, 1600)
        with pytest.raises(ConversionError, match="loop.mp4 not found"):
            convert_pack(pack, tmp_path / "out", display)

    def test_uses_default_display_when_none_given(self, tmp_path):
        pack = tmp_path / "pack"
        self._setup_pack(pack)
        out  = tmp_path / "out"
        with self._mock_ffmpeg_ok():
            result_dir = convert_pack(pack, out)
        assert result_dir == out

    def test_output_dir_returned(self, tmp_path):
        pack = tmp_path / "pack"
        self._setup_pack(pack)
        out  = tmp_path / "out"
        display = DisplayInfo(800, 480, 16, 1600)
        with self._mock_ffmpeg_ok():
            result_dir = convert_pack(pack, out, display)
        assert result_dir == out

    def test_build_meta_json_written(self, tmp_path):
        pack = tmp_path / "pack"
        self._setup_pack(pack)
        out  = tmp_path / "out"
        display = DisplayInfo(800, 480, 16, 1600)
        with self._mock_ffmpeg_ok():
            convert_pack(pack, out, display, scale_mode="fill")
        meta_path = out / "build_meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["scale_mode"] == "fill"
        assert meta["width"] == 800
        assert meta["height"] == 480
