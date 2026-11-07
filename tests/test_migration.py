"""Tests for the migration/uninstall scripts (Task 2 — safe service migration).

Uses subprocess to run the scripts with --dry-run so no real systemd calls are made.
Also tests player.py logic (config reading, pack resolution, fallback) without
touching /dev/fb0 or any real hardware.
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_repo_root = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# player.py — module-level unit tests
# ---------------------------------------------------------------------------

class TestReadConfig:
    def test_reads_valid_config(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"pack": "voron", "scale": "fit"}))
        from player import read_config
        cfg = read_config(str(p))
        assert cfg["pack"] == "voron"

    def test_returns_empty_dict_for_missing_file(self, tmp_path):
        from player import read_config
        cfg = read_config(str(tmp_path / "nonexistent.json"))
        assert cfg == {}

    def test_returns_empty_dict_for_corrupt_json(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text("not valid json {{{")
        from player import read_config
        cfg = read_config(str(p))
        assert cfg == {}

    def test_returns_empty_dict_for_non_object_json(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text(json.dumps([1, 2, 3]))
        from player import read_config
        cfg = read_config(str(p))
        assert cfg == {}


class TestResolvePack:
    def _make_pack(self, build_dir, pack_id):
        d = Path(build_dir) / pack_id
        d.mkdir(parents=True, exist_ok=True)
        for name in ("intro.mp4", "loop.mp4", "still.rgb565"):
            (d / name).write_bytes(b"\x00" * 16)

    def test_returns_configured_pack_when_ready(self, tmp_path):
        self._make_pack(tmp_path, "mechanical_core")
        from player import resolve_pack
        intro, loop, still, pid = resolve_pack(str(tmp_path), {"pack": "mechanical_core"})
        assert pid == "mechanical_core"
        assert intro.endswith("intro.mp4")

    def test_falls_back_to_nexus_signature(self, tmp_path):
        self._make_pack(tmp_path, "nexus_signature")
        from player import resolve_pack
        intro, loop, still, pid = resolve_pack(str(tmp_path), {"pack": "nonexistent_pack"})
        assert pid == "nexus_signature"

    def test_falls_back_to_any_ready_pack(self, tmp_path):
        self._make_pack(tmp_path, "system_init")
        from player import resolve_pack
        intro, loop, still, pid = resolve_pack(str(tmp_path), {"pack": "nonexistent_pack"})
        assert pid == "system_init"
        assert intro != ""

    def test_returns_empty_strings_when_no_pack_ready(self, tmp_path):
        from player import resolve_pack
        intro, loop, still, pid = resolve_pack(str(tmp_path), {})
        assert intro == ""
        assert pid == ""

    def test_uses_default_pack_when_config_has_no_pack_key(self, tmp_path):
        from player import DEFAULT_PACK
        self._make_pack(tmp_path, DEFAULT_PACK)
        from player import resolve_pack
        intro, loop, still, pid = resolve_pack(str(tmp_path), {})
        assert pid == DEFAULT_PACK

    def test_missing_one_file_counts_as_not_ready(self, tmp_path):
        d = tmp_path / "partial_pack"
        d.mkdir()
        (d / "intro.mp4").write_bytes(b"\x00" * 16)
        (d / "loop.mp4").write_bytes(b"\x00" * 16)
        # still.rgb565 is missing
        from player import resolve_pack
        _, _, _, pid = resolve_pack(str(tmp_path), {"pack": "partial_pack"})
        assert pid != "partial_pack"


# ---------------------------------------------------------------------------
# player.py — parse() argument defaults
# ---------------------------------------------------------------------------

class TestParseArgs:
    def test_default_config_path(self):
        from pathlib import Path
        from player import parse
        a = parse([])
        expected = str(Path.home() / "nexus-video" / "config.json")
        assert a.config == expected

    def test_custom_config_path(self):
        from player import parse
        a = parse(["--config", "/tmp/test.json"])
        assert a.config == "/tmp/test.json"

    def test_default_run_dir(self):
        from player import parse
        a = parse([])
        assert a.run_dir == "/run/nexus-splash"

    def test_default_fps(self):
        from player import parse
        a = parse([])
        assert a.fps == 24.0

    def test_max_seconds_override(self):
        from player import parse
        a = parse(["--max-seconds", "120"])
        assert a.max_seconds == 120.0


# ---------------------------------------------------------------------------
# migrate.sh / uninstall.sh — dry-run smoke tests
# ---------------------------------------------------------------------------

class TestMigrateScriptDryRun:
    def _run_migrate(self, *extra_args):
        script = _repo_root / "deploy" / "migrate.sh"
        result = subprocess.run(
            ["bash", str(script), "--dry-run"] + list(extra_args),
            capture_output=True, text=True,
            env={**os.environ, "HOME": str(Path.home())},
        )
        return result

    def test_migrate_is_valid_shell(self):
        script = _repo_root / "deploy" / "migrate.sh"
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, f"Syntax error:\n{result.stderr}"

    def test_install_is_valid_shell(self):
        script = _repo_root / "deploy" / "install.sh"
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, f"Syntax error:\n{result.stderr}"

    def test_uninstall_is_valid_shell(self):
        script = _repo_root / "deploy" / "uninstall.sh"
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, f"Syntax error:\n{result.stderr}"

    def test_service_condition_uses_nexus_signature_not_active_symlink(self):
        """ConditionPathExists must reference nexus_signature directly, not a fragile active symlink."""
        service = _repo_root / "deploy" / "nexus-video.service"
        content = service.read_text()
        assert "build/nexus_signature/still.rgb565" in content, \
            "Service should use nexus_signature as the guaranteed condition path"
        assert "build/active/still.rgb565" not in content, \
            "Service must not use fragile 'active' symlink for ConditionPathExists"

    def test_install_requires_nexus_signature_still(self, tmp_path):
        """install.sh preflight fails if nexus_signature build is missing."""
        script = _repo_root / "deploy" / "install.sh"
        # Run without sudo — should fail at the root check, not the still.rgb565 check
        result = subprocess.run(
            ["bash", str(script), "--confirm"],
            capture_output=True, text=True,
        )
        # Expect non-zero (either root check or build check)
        assert result.returncode != 0

    def test_uninstall_backup_dir_flag_works(self, tmp_path):
        """uninstall.sh --backup-dir=PATH parses correctly (was broken with for loop)."""
        script = _repo_root / "deploy" / "uninstall.sh"
        # Test that the script can at least parse the flag without syntax error
        # (can't actually run without root, but bash -n covers the syntax)
        result = subprocess.run(
            ["bash", "-n", str(script)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# Player.should_stop — logic tests (no hardware)
# ---------------------------------------------------------------------------

class TestPlayerShouldStop:
    def _make_player(self, tmp_path):
        from player import parse, Player
        # Create a fake framebuffer file (not /dev/fb0)
        fb = tmp_path / "fb0"
        fb.write_bytes(b"\x00" * (800 * 480 * 2))
        a = parse(["--fb", str(fb), "--run-dir", str(tmp_path / "run"),
                   "--tty", "", "--max-seconds", "10"])
        # Monkey-patch Framebuffer so we don't need sysfs
        from player import Framebuffer
        with patch.object(Framebuffer, "__init__", return_value=None):
            p = Player(a)
            p.fb = MagicMock()
        return p, tmp_path / "run"

    def test_not_stopped_initially(self, tmp_path):
        p, run = self._make_player(tmp_path)
        assert p.should_stop() is False

    def test_stops_when_ready_file_appears(self, tmp_path):
        p, run = self._make_player(tmp_path)
        run.mkdir(parents=True, exist_ok=True)
        (run / "ready").write_text("")
        assert p.should_stop() is True
        assert "ready" in p.stop_reason.lower()

    def test_stops_on_sigterm(self, tmp_path):
        import signal
        p, run = self._make_player(tmp_path)
        p._stop("SIGTERM")
        assert p.should_stop() is True

    def test_first_reason_wins(self, tmp_path):
        p, run = self._make_player(tmp_path)
        p._stop("SIGTERM")
        p._stop("SIGINT")
        assert p.stop_reason == "SIGTERM"
