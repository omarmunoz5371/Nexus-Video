"""Tests for nexus_video.packs — discovery, validation, manifest."""

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nexus_video.packs import (
    PackInfo, ValidationResult,
    discover_packs, generate_manifest, validate_pack, probe_video,
    VideoProbeError,
)
from nexus_video.config import (
    BUILTIN_DIR, INTRO_FILENAME, LOOP_FILENAME, PACK_META_FILE,
    RECOMMENDED_INTRO_DURATION, RECOMMENDED_LOOP_DURATION,
)
from tests.conftest import needs_ffprobe, HAVE_FFMPEG, HAVE_FFPROBE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_META = {
    "id": "test_pack", "name": "Test Pack",
    "type": "custom", "version": "1.0.0",
    "description": "Test", "intro_duration": 10, "loop_duration": 5,
    "scale_mode": "fit", "trademark_notice": None, "author": None,
    "distribution": "test",
}


def _write_meta(pack_dir: Path, meta: dict = None) -> None:
    (pack_dir / PACK_META_FILE).write_text(json.dumps(meta or VALID_META))


def _fake_ffprobe_output(duration: float = 10.0, width: int = 320, height: int = 240,
                          codec: str = "h264", has_audio: bool = False) -> str:
    streams = [{
        "codec_type": "video", "codec_name": codec,
        "width": width, "height": height,
        "duration": str(duration),
    }]
    if has_audio:
        streams.append({"codec_type": "audio", "codec_name": "aac"})
    return json.dumps({
        "streams": streams,
        "format":  {"duration": str(duration), "filename": "test.mp4"},
    })


def _mock_probe(duration: float = 10.0, width: int = 320, height: int = 240,
                codec: str = "h264", has_audio: bool = False):
    """Context manager: patches subprocess.run to return a successful ffprobe response."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = _fake_ffprobe_output(duration, width, height, codec, has_audio)
    mock_result.stderr = ""
    return patch("nexus_video.packs.subprocess.run", return_value=mock_result)


def _mock_probe_fail(stderr: str = "Invalid data found"):
    """Context manager: patches subprocess.run to simulate an ffprobe failure."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = stderr
    return patch("nexus_video.packs.subprocess.run", return_value=mock_result)


# ---------------------------------------------------------------------------
# probe_video
# ---------------------------------------------------------------------------

class TestProbeVideo:
    def test_returns_video_info_on_valid_output(self, tmp_path):
        p = tmp_path / "clip.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe(duration=10.5, width=800, height=480, codec="h264"):
            info = probe_video(p)
        assert info.duration == pytest.approx(10.5)
        assert info.width == 800
        assert info.height == 480
        assert info.codec == "h264"
        assert info.has_audio is False

    def test_detects_audio_stream(self, tmp_path):
        p = tmp_path / "clip.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe(has_audio=True):
            info = probe_video(p)
        assert info.has_audio is True

    def test_raises_on_nonzero_returncode(self, tmp_path):
        p = tmp_path / "clip.mp4"
        p.write_bytes(b"\x00")
        with _mock_probe_fail("No such file or directory"):
            with pytest.raises(VideoProbeError, match="ffprobe failed"):
                probe_video(p)

    def test_raises_when_no_video_stream(self, tmp_path):
        p = tmp_path / "audio_only.mp4"
        p.write_bytes(b"\x00")
        audio_only_output = json.dumps({
            "streams": [{"codec_type": "audio", "codec_name": "aac"}],
            "format":  {"duration": "30.0"},
        })
        mock_result = MagicMock(returncode=0, stdout=audio_only_output, stderr="")
        with patch("nexus_video.packs.subprocess.run", return_value=mock_result):
            with pytest.raises(VideoProbeError, match="No video stream"):
                probe_video(p)

    def test_raises_when_ffprobe_not_found(self, tmp_path):
        p = tmp_path / "clip.mp4"
        p.write_bytes(b"\x00")
        with patch("nexus_video.packs.subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(VideoProbeError, match="ffprobe not found"):
                probe_video(p)

    def test_raises_on_invalid_json(self, tmp_path):
        p = tmp_path / "clip.mp4"
        p.write_bytes(b"\x00")
        mock_result = MagicMock(returncode=0, stdout="not valid json {{{", stderr="")
        with patch("nexus_video.packs.subprocess.run", return_value=mock_result):
            with pytest.raises(VideoProbeError, match="invalid JSON"):
                probe_video(p)

    def test_raises_on_timeout(self, tmp_path):
        p = tmp_path / "clip.mp4"
        p.write_bytes(b"\x00")
        with patch("nexus_video.packs.subprocess.run", side_effect=subprocess.TimeoutExpired("ffprobe", 15)):
            with pytest.raises(VideoProbeError, match="timed out"):
                probe_video(p)

    @needs_ffprobe
    def test_real_ffprobe_on_invalid_file(self, invalid_video_file):
        """ffprobe on a text file should raise VideoProbeError."""
        with pytest.raises(VideoProbeError):
            probe_video(invalid_video_file)

    @needs_ffprobe
    @pytest.mark.skipif(not HAVE_FFMPEG, reason="needs ffmpeg to generate test fixture")
    def test_real_ffprobe_on_valid_fixture(self, valid_pack_dir):
        intro = valid_pack_dir / INTRO_FILENAME
        if not intro.exists():
            pytest.skip("test fixture video not generated (ffmpeg unavailable)")
        info = probe_video(intro)
        assert info.width > 0
        assert info.height > 0
        assert info.duration > 0.0


# ---------------------------------------------------------------------------
# validate_pack
# ---------------------------------------------------------------------------

class TestValidatePack:
    def test_missing_pack_dir(self, tmp_path):
        result = validate_pack(tmp_path / "nonexistent")
        assert not result.valid
        assert any("not found" in e for e in result.errors)

    def test_missing_pack_json(self, tmp_path):
        pack = tmp_path / "pack"
        pack.mkdir()
        with _mock_probe():
            result = validate_pack(pack)
        assert not result.valid
        assert any(PACK_META_FILE in e for e in result.errors)

    def test_invalid_json_in_pack_meta(self, tmp_path):
        pack = tmp_path / "pack"
        pack.mkdir()
        (pack / PACK_META_FILE).write_text("{invalid json")
        with _mock_probe():
            result = validate_pack(pack)
        assert not result.valid
        assert any("Invalid JSON" in e for e in result.errors)

    def test_missing_required_meta_fields(self, tmp_path):
        pack = tmp_path / "pack"
        pack.mkdir()
        (pack / PACK_META_FILE).write_text(json.dumps({"id": "only_id"}))
        (pack / INTRO_FILENAME).write_bytes(b"\x00")
        (pack / LOOP_FILENAME).write_bytes(b"\x00")
        with _mock_probe():
            result = validate_pack(pack)
        assert not result.valid
        assert any("name" in e for e in result.errors)

    def test_missing_intro_mp4(self, tmp_path):
        pack = tmp_path / "pack"
        pack.mkdir()
        _write_meta(pack)
        (pack / LOOP_FILENAME).write_bytes(b"\x00")
        with _mock_probe():
            result = validate_pack(pack)
        assert not result.valid
        assert any("intro" in e.lower() for e in result.errors)

    def test_missing_loop_mp4(self, tmp_path):
        pack = tmp_path / "pack"
        pack.mkdir()
        _write_meta(pack)
        (pack / INTRO_FILENAME).write_bytes(b"\x00")
        with _mock_probe():
            result = validate_pack(pack)
        assert not result.valid
        assert any("loop" in e.lower() for e in result.errors)

    def test_unsupported_extension_rejected(self, tmp_path):
        pack = tmp_path / "pack"
        pack.mkdir()
        _write_meta(pack)
        (pack / "intro.mp4").write_bytes(b"\x00")
        # Create loop with wrong extension via a different meta
        (pack / PACK_META_FILE).write_text(json.dumps(VALID_META))
        # rename loop.mp4 → loop.avi (supported) then verify .txt is not
        txt_loop = pack / "loop.txt"
        txt_loop.write_text("text")
        # Test specifically that .txt is rejected — patch at the validation layer
        # since we can't rename loop.mp4 to loop.txt and have it be loop.mp4
        from nexus_video import packs as packs_mod
        import nexus_video.packs as packs_module
        orig = packs_module.LOOP_FILENAME
        try:
            packs_module.LOOP_FILENAME = "loop.txt"
            with _mock_probe():
                result = validate_pack(pack)
        finally:
            packs_module.LOOP_FILENAME = orig
        assert not result.valid
        assert any("unsupported extension" in e.lower() for e in result.errors)

    def test_zero_duration_video_rejected(self, tmp_path):
        pack = tmp_path / "pack"
        pack.mkdir()
        _write_meta(pack)
        (pack / INTRO_FILENAME).write_bytes(b"\x00")
        (pack / LOOP_FILENAME).write_bytes(b"\x00")
        with _mock_probe(duration=0.0):
            result = validate_pack(pack)
        assert not result.valid
        assert any("below minimum" in e for e in result.errors)

    def test_duration_warning_for_long_intro(self, tmp_path):
        pack = tmp_path / "pack"
        pack.mkdir()
        _write_meta(pack)
        (pack / INTRO_FILENAME).write_bytes(b"\x00")
        (pack / LOOP_FILENAME).write_bytes(b"\x00")
        with _mock_probe(duration=30.0):  # far from recommended 10s
            result = validate_pack(pack)
        assert result.valid  # still valid
        assert any("duration" in w for w in result.warnings)

    def test_audio_track_generates_warning(self, tmp_path):
        pack = tmp_path / "pack"
        pack.mkdir()
        _write_meta(pack)
        (pack / INTRO_FILENAME).write_bytes(b"\x00")
        (pack / LOOP_FILENAME).write_bytes(b"\x00")
        with _mock_probe(has_audio=True, duration=10.0):
            result = validate_pack(pack)
        assert result.valid  # audio doesn't invalidate the pack
        assert any("audio" in w.lower() for w in result.warnings)

    def test_zero_dimension_video_rejected(self, tmp_path):
        pack = tmp_path / "pack"
        pack.mkdir()
        _write_meta(pack)
        (pack / INTRO_FILENAME).write_bytes(b"\x00")
        (pack / LOOP_FILENAME).write_bytes(b"\x00")
        with _mock_probe(duration=10.0, width=0, height=0):
            result = validate_pack(pack)
        assert not result.valid
        assert any("zero-dimension" in e for e in result.errors)

    def test_valid_pack_passes(self, tmp_path):
        pack = tmp_path / "pack"
        pack.mkdir()
        _write_meta(pack)
        (pack / INTRO_FILENAME).write_bytes(b"\x00")
        (pack / LOOP_FILENAME).write_bytes(b"\x00")
        with _mock_probe(duration=10.0, width=320, height=240):
            result = validate_pack(pack)
        assert result.valid
        assert result.errors == []

    def test_intro_info_populated_on_success(self, tmp_path):
        pack = tmp_path / "pack"
        pack.mkdir()
        _write_meta(pack)
        (pack / INTRO_FILENAME).write_bytes(b"\x00")
        (pack / LOOP_FILENAME).write_bytes(b"\x00")
        with _mock_probe(duration=10.0, width=1920, height=1080):
            result = validate_pack(pack)
        assert result.intro_info is not None
        assert result.intro_info.width == 1920

    @needs_ffprobe
    def test_real_ffprobe_rejects_text_file(self, tmp_path, invalid_video_file):
        pack = tmp_path / "pack"
        pack.mkdir()
        _write_meta(pack)
        shutil.copy(invalid_video_file, pack / INTRO_FILENAME)
        shutil.copy(invalid_video_file, pack / LOOP_FILENAME)
        result = validate_pack(pack)
        assert not result.valid
        assert any("probe failed" in e for e in result.errors)


# ---------------------------------------------------------------------------
# discover_packs
# ---------------------------------------------------------------------------

class TestDiscoverPacks:
    def test_discovers_builtin_packs(self):
        packs = discover_packs(builtin_dir=BUILTIN_DIR, custom_dir=BUILTIN_DIR.parent / "custom")
        pack_ids = [p.pack_id for p in packs]
        for expected_id in ("nexus_signature", "mechanical_core", "system_init"):
            assert expected_id in pack_ids
        # voron pack is excluded from public distribution (pending trademark review)

    def test_discover_returns_empty_for_missing_dirs(self, tmp_path):
        packs = discover_packs(
            builtin_dir=tmp_path / "no_builtin",
            custom_dir=tmp_path / "no_custom",
        )
        assert packs == []

    def test_discover_ignores_dirs_without_pack_json(self, tmp_path):
        builtin = tmp_path / "builtin"
        (builtin / "not_a_pack").mkdir(parents=True)
        packs = discover_packs(builtin_dir=builtin, custom_dir=tmp_path / "custom")
        assert packs == []

    def test_discover_finds_custom_packs(self, tmp_path):
        custom = tmp_path / "custom"
        pack1  = custom / "my_pack"
        pack1.mkdir(parents=True)
        (pack1 / PACK_META_FILE).write_text(json.dumps({
            **VALID_META, "id": "my_pack", "type": "custom"
        }))
        packs = discover_packs(builtin_dir=tmp_path / "builtin", custom_dir=custom)
        assert len(packs) == 1
        assert packs[0].pack_id == "my_pack"
        assert packs[0].pack_type == "custom"

    def test_builtin_packs_come_before_custom(self, tmp_path):
        builtin = tmp_path / "builtin"
        custom  = tmp_path / "custom"
        (builtin / "aaa_builtin").mkdir(parents=True)
        (custom  / "zzz_custom").mkdir(parents=True)
        (builtin / "aaa_builtin" / PACK_META_FILE).write_text(
            json.dumps({**VALID_META, "id": "aaa_builtin", "type": "builtin"})
        )
        (custom / "zzz_custom" / PACK_META_FILE).write_text(
            json.dumps({**VALID_META, "id": "zzz_custom", "type": "custom"})
        )
        packs = discover_packs(builtin_dir=builtin, custom_dir=custom)
        assert packs[0].pack_type == "builtin"
        assert packs[-1].pack_type == "custom"

    def test_packs_sorted_alphabetically_within_type(self, tmp_path):
        builtin = tmp_path / "builtin"
        for name in ("zzz", "aaa", "mmm"):
            d = builtin / name
            d.mkdir(parents=True)
            (d / PACK_META_FILE).write_text(json.dumps({**VALID_META, "id": name}))
        packs = discover_packs(builtin_dir=builtin, custom_dir=tmp_path / "custom")
        assert [p.pack_id for p in packs] == ["aaa", "mmm", "zzz"]

    def test_type_hint_applied_when_meta_missing_type(self, tmp_path):
        custom = tmp_path / "custom"
        pack   = custom / "untyped_pack"
        pack.mkdir(parents=True)
        meta_no_type = {k: v for k, v in VALID_META.items() if k != "type"}
        (pack / PACK_META_FILE).write_text(json.dumps(meta_no_type))
        packs = discover_packs(builtin_dir=tmp_path / "builtin", custom_dir=custom)
        assert len(packs) == 1
        assert packs[0].pack_type == "custom"


# ---------------------------------------------------------------------------
# generate_manifest
# ---------------------------------------------------------------------------

class TestGenerateManifest:
    def test_manifest_has_schema_version(self):
        manifest = generate_manifest(validate=False)
        assert "schema_version" in manifest
        assert manifest["schema_version"] == "1.0"

    def test_manifest_includes_all_builtin_packs(self):
        manifest = generate_manifest(validate=False)
        ids = [e["id"] for e in manifest["packs"]]
        for expected in ("nexus_signature", "mechanical_core", "system_init", "voron"):
            assert expected in ids

    def test_manifest_pack_count_matches_list(self):
        manifest = generate_manifest(validate=False)
        assert manifest["pack_count"] == len(manifest["packs"])

    def test_manifest_entry_has_required_keys(self):
        manifest = generate_manifest(validate=False)
        for entry in manifest["packs"]:
            for key in ("id", "name", "type", "pack_dir", "valid", "errors", "warnings", "meta"):
                assert key in entry, f"Missing key '{key}' in pack entry {entry.get('id')}"

    def test_manifest_voron_has_trademark_notice(self):
        manifest = generate_manifest(validate=False)
        voron = next((e for e in manifest["packs"] if e["id"] == "voron"), None)
        assert voron is not None
        assert voron["meta"]["trademark_notice"] is not None
        assert voron["meta"]["distribution"] == "pending_trademark_review"

    def test_manifest_validate_false_skips_ffprobe(self):
        """With validate=False, we should not invoke ffprobe."""
        with patch("nexus_video.packs.validate_pack") as mock_validate:
            generate_manifest(validate=False)
            mock_validate.assert_not_called()

    def test_manifest_custom_packs_included(self, tmp_path):
        custom = tmp_path / "custom"
        pack   = custom / "extra_pack"
        pack.mkdir(parents=True)
        (pack / PACK_META_FILE).write_text(json.dumps({**VALID_META, "id": "extra_pack"}))
        manifest = generate_manifest(builtin_dir=BUILTIN_DIR, custom_dir=custom, validate=False)
        ids = [e["id"] for e in manifest["packs"]]
        assert "extra_pack" in ids
