"""Tests for nexus_video.settings_bridge — pure Python, no Qt required."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from nexus_video.settings_bridge import (
    DEFAULT_PACK, DEFAULT_SCALE, PREF_PACK, PREF_SCALE, VALID_SCALES,
    _write_service_config, build_is_ready, get_selection, set_selection,
)


# ---------------------------------------------------------------------------
# get_selection — defaults when prefs file absent or empty
# ---------------------------------------------------------------------------

class TestGetSelection:
    def test_returns_defaults_when_no_prefs_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "nexus_video.settings_bridge.PREFS_PATH",
            tmp_path / "nonexistent.json",
        )
        pack, scale = get_selection()
        assert pack  == DEFAULT_PACK
        assert scale == DEFAULT_SCALE

    def test_returns_stored_values(self, tmp_path, monkeypatch):
        p = tmp_path / "preferences.json"
        p.write_text(json.dumps({PREF_PACK: "voron", PREF_SCALE: "fill"}))
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", p)
        pack, scale = get_selection()
        assert pack  == "voron"
        assert scale == "fill"

    def test_invalid_scale_falls_back_to_default(self, tmp_path, monkeypatch):
        p = tmp_path / "preferences.json"
        p.write_text(json.dumps({PREF_PACK: "nexus_signature", PREF_SCALE: "zoom"}))
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", p)
        _, scale = get_selection()
        assert scale == DEFAULT_SCALE

    def test_survives_corrupt_json(self, tmp_path, monkeypatch):
        p = tmp_path / "preferences.json"
        p.write_text("not valid json {{{")
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", p)
        pack, scale = get_selection()
        assert pack  == DEFAULT_PACK
        assert scale == DEFAULT_SCALE

    def test_unrelated_prefs_keys_are_preserved(self, tmp_path, monkeypatch):
        p = tmp_path / "preferences.json"
        prefs = {"timeout_min": 10, "brightness": 80, PREF_PACK: "system_init", PREF_SCALE: "stretch"}
        p.write_text(json.dumps(prefs))
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", p)
        pack, scale = get_selection()
        assert pack  == "system_init"
        assert scale == "stretch"


# ---------------------------------------------------------------------------
# set_selection — writes prefs and optionally service config
# ---------------------------------------------------------------------------

class TestSetSelection:
    def test_writes_pack_and_scale_to_prefs(self, tmp_path, monkeypatch):
        p = tmp_path / "preferences.json"
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", p)
        set_selection("mechanical_core", "fill")
        saved = json.loads(p.read_text())
        assert saved[PREF_PACK]  == "mechanical_core"
        assert saved[PREF_SCALE] == "fill"

    def test_preserves_unrelated_prefs(self, tmp_path, monkeypatch):
        p = tmp_path / "preferences.json"
        p.write_text(json.dumps({"timeout_min": 15, "brightness": 70}))
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", p)
        set_selection("nexus_signature", "fit")
        saved = json.loads(p.read_text())
        assert saved["timeout_min"] == 15
        assert saved["brightness"]  == 70

    def test_raises_on_invalid_scale(self, tmp_path, monkeypatch):
        p = tmp_path / "preferences.json"
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", p)
        with pytest.raises(ValueError, match="Invalid scale mode"):
            set_selection("nexus_signature", "zoom")

    def test_all_valid_scales_accepted(self, tmp_path, monkeypatch):
        p = tmp_path / "preferences.json"
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", p)
        for scale in VALID_SCALES:
            set_selection("nexus_signature", scale)
            _, saved_scale = get_selection()
            assert saved_scale == scale

    def test_creates_parent_dirs(self, tmp_path, monkeypatch):
        p = tmp_path / "deep" / "config" / "preferences.json"
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", p)
        set_selection("nexus_signature", "fit")
        assert p.exists()

    def test_writes_service_config_when_path_given(self, tmp_path, monkeypatch):
        prefs = tmp_path / "preferences.json"
        svc   = tmp_path / "service" / "config.json"
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", prefs)
        set_selection("voron", "stretch", service_config_path=svc)
        cfg = json.loads(svc.read_text())
        assert cfg["pack"]  == "voron"
        assert cfg["scale"] == "stretch"

    def test_no_service_config_written_when_path_is_none(self, tmp_path, monkeypatch):
        prefs = tmp_path / "preferences.json"
        svc   = tmp_path / "config.json"
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", prefs)
        set_selection("nexus_signature", "fit", service_config_path=None)
        assert not svc.exists()


# ---------------------------------------------------------------------------
# _write_service_config
# ---------------------------------------------------------------------------

class TestWriteServiceConfig:
    def test_writes_expected_fields(self, tmp_path):
        p = tmp_path / "config.json"
        _write_service_config("mechanical_core", "fill", p)
        cfg = json.loads(p.read_text())
        assert cfg == {"pack": "mechanical_core", "scale": "fill"}

    def test_creates_parent_directory(self, tmp_path):
        p = tmp_path / "nested" / "sub" / "config.json"
        _write_service_config("nexus_signature", "fit", p)
        assert p.exists()

    def test_overwrites_existing_config(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"pack": "old", "scale": "stretch"}))
        _write_service_config("system_init", "fill", p)
        cfg = json.loads(p.read_text())
        assert cfg["pack"] == "system_init"


# ---------------------------------------------------------------------------
# build_is_ready
# ---------------------------------------------------------------------------

class TestBuildIsReady:
    def test_returns_true_when_all_files_present(self, tmp_path):
        pack_dir = tmp_path / "nexus_signature"
        pack_dir.mkdir()
        for name in ("intro.mp4", "loop.mp4", "still.rgb565"):
            (pack_dir / name).write_bytes(b"\x00")
        assert build_is_ready(tmp_path, "nexus_signature") is True

    def test_returns_false_when_intro_missing(self, tmp_path):
        pack_dir = tmp_path / "nexus_signature"
        pack_dir.mkdir()
        (pack_dir / "loop.mp4").write_bytes(b"\x00")
        (pack_dir / "still.rgb565").write_bytes(b"\x00")
        assert build_is_ready(tmp_path, "nexus_signature") is False

    def test_returns_false_when_loop_missing(self, tmp_path):
        pack_dir = tmp_path / "nexus_signature"
        pack_dir.mkdir()
        (pack_dir / "intro.mp4").write_bytes(b"\x00")
        (pack_dir / "still.rgb565").write_bytes(b"\x00")
        assert build_is_ready(tmp_path, "nexus_signature") is False

    def test_returns_false_when_still_missing(self, tmp_path):
        pack_dir = tmp_path / "nexus_signature"
        pack_dir.mkdir()
        (pack_dir / "intro.mp4").write_bytes(b"\x00")
        (pack_dir / "loop.mp4").write_bytes(b"\x00")
        assert build_is_ready(tmp_path, "nexus_signature") is False

    def test_returns_false_when_pack_dir_missing(self, tmp_path):
        assert build_is_ready(tmp_path, "nonexistent") is False

    def test_uses_correct_pack_id_subdirectory(self, tmp_path):
        for pid in ("nexus_signature", "mechanical_core"):
            d = tmp_path / pid
            d.mkdir()
            for name in ("intro.mp4", "loop.mp4", "still.rgb565"):
                (d / name).write_bytes(b"\x00")
        assert build_is_ready(tmp_path, "nexus_signature") is True
        assert build_is_ready(tmp_path, "mechanical_core") is True

    def test_live_build_dir_has_all_four_packs_ready(self):
        """Integration check: our Phase 3B builds are all present."""
        from nexus_video.config import BUILD_DIR
        for pack_id in ("nexus_signature", "mechanical_core", "system_init", "voron"):
            assert build_is_ready(BUILD_DIR, pack_id), \
                f"Pack {pack_id} is not ready in {BUILD_DIR}"
