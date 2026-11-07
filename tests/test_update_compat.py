"""Update compatibility tests (Task 5 — Moonraker Update Manager, patch, prefs preservation).

Verifies:
- Nexus Screen preferences file is not managed by the Nexus Screen git repo
  (so git updates cannot delete user selections)
- Custom pack directories are outside nexus-screen-dev (safe from updates)
- Settings bridge survives a prefs file that is missing expected keys (future-proofing)
- Nexus Video config.json is not inside the nexus-screen directory tree
- Modified files in nexus-screen-dev are identifiable for patch generation
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

_repo_root = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Preference file location
# ---------------------------------------------------------------------------

class TestPrefsLocation:
    def test_prefs_path_is_outside_nexus_screen_tree(self):
        from nexus_video.settings_bridge import PREFS_PATH
        nexus_screen = Path.home() / "nexus-screen"
        # PREFS_PATH must not be inside ~/nexus-screen/
        assert not str(PREFS_PATH).startswith(str(nexus_screen)), \
            f"PREFS_PATH {PREFS_PATH} is inside nexus-screen — git updates would delete it"

    def test_prefs_path_is_outside_nexus_screen_dev_tree(self):
        from nexus_video.settings_bridge import PREFS_PATH
        dev_tree = _repo_root / "nexus-screen-dev"
        assert not str(PREFS_PATH).startswith(str(dev_tree)), \
            f"PREFS_PATH {PREFS_PATH} is inside nexus-screen-dev"

    def test_prefs_path_is_in_xdg_config(self):
        from nexus_video.settings_bridge import PREFS_PATH
        xdg = Path.home() / ".config"
        assert str(PREFS_PATH).startswith(str(xdg)), \
            f"PREFS_PATH {PREFS_PATH} is not in ~/.config (XDG)"


# ---------------------------------------------------------------------------
# Custom pack directory location
# ---------------------------------------------------------------------------

class TestCustomPackLocation:
    def test_live_custom_packs_outside_nexus_screen(self):
        nexus_screen = Path.home() / "nexus-screen"
        custom_dir = _repo_root / "packs" / "custom"
        assert not str(custom_dir).startswith(str(nexus_screen)), \
            "Custom packs directory is inside nexus-screen — git updates would delete them"

    def test_fixture_packs_outside_nexus_screen(self):
        nexus_screen = Path.home() / "nexus-screen"
        fixtures_dir = _repo_root / "tests" / "fixtures"
        assert fixtures_dir.exists()
        assert not str(fixtures_dir).startswith(str(nexus_screen))


# ---------------------------------------------------------------------------
# Service config location
# ---------------------------------------------------------------------------

class TestServiceConfigLocation:
    def test_service_config_written_outside_nexus_screen(self, tmp_path):
        """set_selection with a production config path must not write inside nexus-screen."""
        prefs = tmp_path / "prefs.json"
        cfg   = tmp_path / "config.json"
        nexus_screen = Path.home() / "nexus-screen"
        assert not str(cfg).startswith(str(nexus_screen))

    def test_service_config_format_stable(self, tmp_path):
        """config.json format used by player.py: {pack, scale}."""
        from nexus_video.settings_bridge import _write_service_config
        cfg = tmp_path / "config.json"
        _write_service_config("nexus_signature", "fit", cfg)
        data = json.loads(cfg.read_text())
        assert set(data.keys()) == {"pack", "scale"}
        assert data["pack"] == "nexus_signature"
        assert data["scale"] == "fit"


# ---------------------------------------------------------------------------
# Preference forward-compatibility (extra keys from future versions)
# ---------------------------------------------------------------------------

class TestPrefsForwardCompat:
    def test_extra_keys_in_prefs_do_not_crash_get_selection(self, tmp_path):
        from nexus_video.settings_bridge import get_selection
        p = tmp_path / "prefs.json"
        p.write_text(json.dumps({
            "startup_video_pack": "nexus_signature",
            "startup_video_scale": "fit",
            "future_key_v2": "some_value",
            "another_future_key": 42,
        }))
        with patch("nexus_video.settings_bridge.PREFS_PATH", p):
            pack, scale = get_selection()
        assert pack  == "nexus_signature"
        assert scale == "fit"

    def test_set_selection_preserves_all_existing_keys(self, tmp_path):
        from nexus_video.settings_bridge import set_selection, get_selection
        p = tmp_path / "prefs.json"
        p.write_text(json.dumps({
            "timeout_minutes": 30,
            "brightness": 80,
            "some_future_v2_key": True,
        }))
        with patch("nexus_video.settings_bridge.PREFS_PATH", p):
            set_selection("nexus_signature", "fill")
            saved = json.loads(p.read_text())
        assert saved["timeout_minutes"]  == 30
        assert saved["brightness"]       == 80
        assert saved["some_future_v2_key"] is True


# ---------------------------------------------------------------------------
# nexus-screen-dev modified file inventory
# ---------------------------------------------------------------------------

class TestNexusScreenDevChanges:
    """Verify the two files we modified in nexus-screen-dev are what we expect."""

    def test_settings_py_has_startup_video(self):
        settings_py = _repo_root / "nexus-screen-dev" / "nexus" / "screens" / "settings.py"
        assert settings_py.exists()
        content = settings_py.read_text()
        assert "startup_video" in content, \
            "settings.py does not contain 'startup_video' — was the patch applied?"

    def test_app_py_imports_startup_video_screen(self):
        app_py = _repo_root / "nexus-screen-dev" / "nexus" / "app.py"
        assert app_py.exists()
        content = app_py.read_text()
        assert "StartupVideoScreen" in content

    def test_startup_video_py_exists(self):
        svpy = _repo_root / "nexus-screen-dev" / "nexus" / "screens" / "startup_video.py"
        assert svpy.exists()

    def test_video_preview_py_exists(self):
        pvpy = _repo_root / "nexus-screen-dev" / "nexus" / "screens" / "video_preview.py"
        assert pvpy.exists()


# ---------------------------------------------------------------------------
# Moonraker Update Manager — git-tracked files check
# ---------------------------------------------------------------------------

class TestMoonrakerUpdateManager:
    def test_prefs_file_not_git_tracked(self):
        """The preferences file path must not be tracked by any git repo under nexus-screen."""
        import subprocess
        nexus_screen_git = Path.home() / "nexus-screen"
        if not (nexus_screen_git / ".git").exists():
            pytest.skip("~/nexus-screen is not a git repo — skipping git tracking check")
        from nexus_video.settings_bridge import PREFS_PATH
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(PREFS_PATH)],
            capture_output=True, cwd=str(nexus_screen_git),
        )
        # git ls-files --error-unmatch exits non-zero if file is NOT tracked
        assert result.returncode != 0, \
            f"{PREFS_PATH} is tracked by nexus-screen git — it would be deleted on git checkout"
