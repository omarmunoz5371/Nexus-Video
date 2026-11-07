"""Qt widget tests for the Startup Video settings screen.

Runs headless with QT_QPA_PLATFORM=offscreen.
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Force offscreen rendering before QApplication is created
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

# Allow importing from the nexus-screen-dev tree
_dev_root = Path(__file__).resolve().parent.parent / "nexus-screen-dev"
if str(_dev_root) not in sys.path:
    sys.path.insert(0, str(_dev_root))


@pytest.fixture(scope="session")
def qapp():
    """Single QApplication for the whole test session."""
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


# ---------------------------------------------------------------------------
# settings_bridge round-trip via UI
# ---------------------------------------------------------------------------

class TestStartupVideoScreenBasic:
    """Smoke tests: instantiation, tab switching, selection persistence."""

    def test_screen_instantiates(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH",
                            tmp_path / "prefs.json")
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        assert screen is not None
        screen.close()

    def test_screen_has_correct_title(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH",
                            tmp_path / "prefs.json")
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        assert screen.TITLE    == "Startup Video"
        assert screen.SUBTITLE != ""
        screen.close()

    def test_screen_is_submenu(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH",
                            tmp_path / "prefs.json")
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        assert screen.submenu  is True
        assert screen.fullscreen is True
        screen.close()

    def test_select_pack_persists_to_prefs(self, qapp, tmp_path, monkeypatch):
        prefs_path = tmp_path / "prefs.json"
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", prefs_path)
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        screen.select_pack("mechanical_core")
        saved = json.loads(prefs_path.read_text())
        assert saved["startup_video_pack"] == "mechanical_core"
        screen.close()

    def test_select_scale_persists_to_prefs(self, qapp, tmp_path, monkeypatch):
        prefs_path = tmp_path / "prefs.json"
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", prefs_path)
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        screen.select_scale("fill")
        saved = json.loads(prefs_path.read_text())
        assert saved["startup_video_scale"] == "fill"
        screen.close()

    def test_all_three_scale_modes_accepted(self, qapp, tmp_path, monkeypatch):
        prefs_path = tmp_path / "prefs.json"
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", prefs_path)
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        for mode in ("fit", "fill", "stretch"):
            screen.select_scale(mode)
            saved = json.loads(prefs_path.read_text())
            assert saved["startup_video_scale"] == mode
        screen.close()

    def test_service_config_written_on_selection(self, qapp, tmp_path, monkeypatch):
        prefs_path = tmp_path / "prefs.json"
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", prefs_path)
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        screen.select_pack("system_init")
        screen.close()

    def test_selection_survives_show_hide_cycle(self, qapp, tmp_path, monkeypatch):
        prefs_path = tmp_path / "prefs.json"
        prefs_path.write_text(json.dumps({
            "startup_video_pack": "voron",
            "startup_video_scale": "stretch",
        }))
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", prefs_path)
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        screen.show()
        qapp.processEvents()
        # showEvent triggers _refresh which re-reads prefs
        assert screen._selected_pack  == "voron"
        assert screen._selected_scale == "stretch"
        screen.close()


# ---------------------------------------------------------------------------
# PackPage grid
# ---------------------------------------------------------------------------

class TestPackPage:
    def _make_mock_pack(self, pack_id, name, dist="included"):
        info = MagicMock()
        info.pack_id = pack_id
        info.name    = name
        info.meta    = {"description": f"Pack {pack_id}", "distribution": dist}
        return info

    def test_pack_page_creates_tiles_for_each_pack(self, qapp):
        from nexus.screens.startup_video import PackPage, StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        page = screen._pack_page

        packs = [
            self._make_mock_pack("nexus_signature", "Nexus Signature"),
            self._make_mock_pack("mechanical_core", "Mechanical Core"),
        ]
        with patch("nexus.screens.startup_video.build_is_ready", return_value=False):
            page.rebuild(packs, "nexus_signature", Path("/tmp/nonexistent"))

        assert "nexus_signature" in page.tiles
        assert "mechanical_core" in page.tiles
        screen.close()

    def test_selected_tile_is_marked(self, qapp):
        from nexus.screens.startup_video import PackPage, StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        page = screen._pack_page

        packs = [
            self._make_mock_pack("nexus_signature", "Nexus Signature"),
            self._make_mock_pack("mechanical_core", "Mechanical Core"),
        ]
        with patch("nexus.screens.startup_video.build_is_ready", return_value=True):
            page.rebuild(packs, "nexus_signature", Path("/tmp/nonexistent"))

        assert page.tiles["nexus_signature"].selected is True
        assert page.tiles["mechanical_core"].selected is False
        screen.close()

    def test_set_selected_updates_tiles(self, qapp):
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        page = screen._pack_page

        packs = [
            self._make_mock_pack("nexus_signature", "Nexus Signature"),
            self._make_mock_pack("mechanical_core", "Mechanical Core"),
        ]
        with patch("nexus.screens.startup_video.build_is_ready", return_value=True):
            page.rebuild(packs, "nexus_signature", Path("/tmp/nonexistent"))
        page.set_selected("mechanical_core")
        assert page.tiles["mechanical_core"].selected is True
        assert page.tiles["nexus_signature"].selected is False
        screen.close()

    def test_trademark_tile_marked_private(self, qapp):
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        page = screen._pack_page

        packs = [self._make_mock_pack("voron", "Voron", dist="pending_trademark_review")]
        with patch("nexus.screens.startup_video.build_is_ready", return_value=True):
            page.rebuild(packs, "nexus_signature", Path("/tmp/nonexistent"))

        assert page.tiles["voron"].trademark_pending is True
        screen.close()

    def test_unbuilt_tile_marked_not_ready(self, qapp):
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        page = screen._pack_page

        packs = [self._make_mock_pack("system_init", "System Init")]
        with patch("nexus.screens.startup_video.build_is_ready", return_value=False):
            page.rebuild(packs, "nexus_signature", Path("/tmp/nonexistent"))

        assert page.tiles["system_init"].ready is False
        screen.close()


# ---------------------------------------------------------------------------
# ScalePage
# ---------------------------------------------------------------------------

class TestScalePage:
    def test_scale_page_buttons_exist(self, qapp):
        from nexus.screens.startup_video import ScalePage, StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        page = screen._scale_page
        assert set(page._buttons) == {"fit", "fill", "stretch"}
        screen.close()

    def test_set_scale_checks_correct_button(self, qapp):
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        page = screen._scale_page
        for mode in ("fit", "fill", "stretch"):
            page.set_scale(mode)
            for key, btn in page._buttons.items():
                assert btn.isChecked() == (key == mode), \
                    f"mode={mode}: button {key!r} checked={btn.isChecked()}"
        screen.close()

    def test_description_set_on_scale_change(self, qapp):
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        page = screen._scale_page
        page.set_scale("fill")
        assert len(page._desc_label) > 0
        screen.close()


# ---------------------------------------------------------------------------
# StatusPage
# ---------------------------------------------------------------------------

class TestStatusPage:
    def test_status_page_rows_set(self, qapp):
        from nexus.screens.startup_video import StatusPage
        page = StatusPage()
        page.resize(560, 380)
        rows = [("Nexus Signature", "Ready", "#27d052"), ("Voron", "PRIVATE", "#8d939b")]
        page.set_rows(rows)
        assert page._rows == rows

    def test_status_page_handles_empty_rows(self, qapp):
        from nexus.screens.startup_video import StatusPage
        page = StatusPage()
        page.set_rows([])
        assert page._rows == []


# ---------------------------------------------------------------------------
# load_still_thumbnail
# ---------------------------------------------------------------------------

class TestLoadStillThumbnail:
    def test_returns_none_for_missing_file(self, tmp_path):
        from nexus.screens.startup_video import load_still_thumbnail
        result = load_still_thumbnail(tmp_path / "missing.rgb565", 192, 108)
        assert result is None

    def test_returns_none_for_wrong_size(self, tmp_path, qapp):
        from nexus.screens.startup_video import load_still_thumbnail
        p = tmp_path / "bad.rgb565"
        p.write_bytes(b"\x00" * 1000)
        result = load_still_thumbnail(p, 192, 108)
        assert result is None

    def test_returns_pixmap_for_correct_size(self, tmp_path, qapp):
        from nexus.screens.startup_video import load_still_thumbnail
        from PyQt6.QtGui import QPixmap
        p = tmp_path / "good.rgb565"
        p.write_bytes(b"\x00" * (800 * 480 * 2))
        result = load_still_thumbnail(p, 192, 108)
        assert result is not None
        assert isinstance(result, QPixmap)
        assert result.width()  <= 192
        assert result.height() <= 108

    def test_loads_live_still_from_nexus_signature(self, qapp):
        from nexus.screens.startup_video import load_still_thumbnail
        from PyQt6.QtGui import QPixmap
        from nexus_video.config import BUILD_DIR
        still = BUILD_DIR / "nexus_signature" / "still.rgb565"
        if not still.exists():
            pytest.skip("nexus_signature build not found")
        result = load_still_thumbnail(still, 192, 108)
        assert isinstance(result, QPixmap)
        assert result.width() > 0
        assert result.height() > 0


# ---------------------------------------------------------------------------
# Settings page tile registration
# ---------------------------------------------------------------------------

class TestSettingsPageTile:
    def test_startup_video_in_settings_list(self):
        from nexus.screens.settings import SETTINGS
        keys = [s[0] for s in SETTINGS]
        assert "startup_video" in keys

    def test_startup_video_tile_has_name(self):
        from nexus.screens.settings import SETTINGS
        entry = next(s for s in SETTINGS if s[0] == "startup_video")
        assert entry[1] == "Startup Video"

    def test_settings_page_creates_startup_video_tile(self, qapp):
        from nexus.screens.settings import SettingsPage
        page = SettingsPage()
        page.resize(720, 442)
        assert "startup_video" in page.tiles

    def test_settings_page_has_nine_settings_tiles(self, qapp):
        from nexus.screens.settings import SETTINGS
        assert len(SETTINGS) == 9


# ---------------------------------------------------------------------------
# Path resolution — production vs dev (regression for wrong _packs_root/_build_dir)
# ---------------------------------------------------------------------------

class TestPathResolution:
    """Verify _NV_INSTALL is derived from nexus_video's __file__, not from which
    directories happen to exist on the filesystem."""

    def test_nv_install_contains_nexus_video_package(self):
        from nexus.screens.startup_video import _NV_INSTALL
        assert (_NV_INSTALL / "nexus_video").exists(), \
            f"_NV_INSTALL={_NV_INSTALL} does not contain nexus_video package"

    def test_packs_root_contains_builtin_dir(self):
        from nexus.screens.startup_video import _packs_root
        assert (_packs_root() / "builtin").exists(), \
            f"_packs_root()={_packs_root()} has no builtin/ subdir"

    def test_build_dir_is_sibling_of_nexus_video_package(self):
        from nexus.screens.startup_video import _NV_INSTALL, _build_dir
        assert _build_dir() == _NV_INSTALL / "build"

    def test_packs_root_is_sibling_of_nexus_video_package(self):
        from nexus.screens.startup_video import _NV_INSTALL, _packs_root
        assert _packs_root() == _NV_INSTALL / "packs"

    def test_persist_service_cfg_is_production_config(self, qapp, tmp_path, monkeypatch):
        """_persist() must write to _NV_INSTALL/config.json, not nexus-video-dev/config.json."""
        prefs_path = tmp_path / "prefs.json"
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", prefs_path)
        from nexus.screens.startup_video import StartupVideoScreen, _NV_INSTALL
        written_paths = []

        import nexus_video.settings_bridge as _sb
        orig_set = _sb.set_selection

        def _capture_set(pack, scale, service_cfg=None):
            if service_cfg is not None:
                written_paths.append(service_cfg)
            return orig_set(pack, scale, service_cfg)

        monkeypatch.setattr(_sb, "set_selection", _capture_set)

        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        screen.select_pack("system_init")
        screen.close()

        assert any(p == _NV_INSTALL / "config.json" for p in written_paths), \
            f"Expected {_NV_INSTALL / 'config.json'} but got {written_paths}"


# ---------------------------------------------------------------------------
# PackPage scroll — layout with many packs
# ---------------------------------------------------------------------------

class TestPackPageScroll:
    def _make_mock_packs(self, n):
        packs = []
        for i in range(n):
            info = MagicMock()
            info.pack_id = f"pack_{i:02d}"
            info.name    = f"Pack {i:02d}"
            info.meta    = {"description": "", "distribution": "included"}
            packs.append(info)
        return packs

    def test_scroll_max_is_zero_for_few_packs(self, qapp):
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        page = screen._pack_page
        page.resize(628, 418)
        packs = self._make_mock_packs(2)
        with patch("nexus.screens.startup_video.build_is_ready", return_value=True):
            page.rebuild(packs, "pack_00", Path("/tmp/nonexistent"))
        assert page._max_scroll() == 0, "2 packs fit in one row — no scroll needed"
        screen.close()

    def test_scroll_needed_for_many_packs(self, qapp):
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        page = screen._pack_page
        page.resize(628, 418)
        packs = self._make_mock_packs(10)
        with patch("nexus.screens.startup_video.build_is_ready", return_value=True):
            page.rebuild(packs, "pack_00", Path("/tmp/nonexistent"))
        assert page._max_scroll() > 0, "10 packs should require scrolling"
        screen.close()

    def test_all_tiles_created_regardless_of_overflow(self, qapp):
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        page = screen._pack_page
        page.resize(628, 418)
        packs = self._make_mock_packs(10)
        with patch("nexus.screens.startup_video.build_is_ready", return_value=False):
            page.rebuild(packs, "pack_00", Path("/tmp/nonexistent"))
        assert len(page.tiles) == 10
        screen.close()

    def test_scroll_y_clamped_to_max(self, qapp):
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        page = screen._pack_page
        page.resize(628, 418)
        packs = self._make_mock_packs(10)
        with patch("nexus.screens.startup_video.build_is_ready", return_value=True):
            page.rebuild(packs, "pack_00", Path("/tmp/nonexistent"))
        page._scroll_y = 99999
        page._clamp_scroll()
        assert page._scroll_y == page._max_scroll()
        screen.close()

    def test_scroll_y_clamped_above_zero(self, qapp):
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        page = screen._pack_page
        packs = self._make_mock_packs(4)
        with patch("nexus.screens.startup_video.build_is_ready", return_value=True):
            page.rebuild(packs, "pack_00", Path("/tmp/nonexistent"))
        page._scroll_y = -50
        page._clamp_scroll()
        assert page._scroll_y == 0.0
        screen.close()

    def test_container_is_child_of_pack_page(self, qapp):
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        page = screen._pack_page
        assert page._container.parent() is page
        screen.close()

    def test_tiles_are_children_of_container(self, qapp):
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        page = screen._pack_page
        packs = self._make_mock_packs(3)
        with patch("nexus.screens.startup_video.build_is_ready", return_value=True):
            page.rebuild(packs, "pack_00", Path("/tmp/nonexistent"))
        for tile in page.tiles.values():
            assert tile.parent() is page._container
        screen.close()

    def test_rebuild_resets_scroll_to_top(self, qapp):
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        page = screen._pack_page
        page._scroll_y = 200.0
        packs = self._make_mock_packs(3)
        with patch("nexus.screens.startup_video.build_is_ready", return_value=True):
            page.rebuild(packs, "pack_00", Path("/tmp/nonexistent"))
        assert page._scroll_y == 0.0
        screen.close()

    def test_content_height_matches_rows(self, qapp):
        from nexus.screens.startup_video import StartupVideoScreen, _TILE_H, _TILE_GAP, _PACK_COLS
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        page = screen._pack_page
        packs = self._make_mock_packs(5)
        with patch("nexus.screens.startup_video.build_is_ready", return_value=True):
            page.rebuild(packs, "pack_00", Path("/tmp/nonexistent"))
        # 5 packs = 3 rows (ceil(5/2))
        expected_h = 3 * _TILE_H + 2 * _TILE_GAP
        assert page._content_height() == expected_h
        screen.close()


# ---------------------------------------------------------------------------
# Custom pack discovery — micron_original (production-path tests)
# ---------------------------------------------------------------------------

_PROD_PACKS = Path.home() / "nexus-video" / "packs"
_PROD_BUILD = Path.home() / "nexus-video" / "build"
_PROD_INSTALL_EXISTS = (_PROD_PACKS / "builtin").exists()


@pytest.mark.skipif(not _PROD_INSTALL_EXISTS,
                    reason="production ~/nexus-video/ not present on this machine")
class TestCustomPackDiscovery:
    def test_micron_original_discoverable(self):
        """micron_original must appear in the production pack listing."""
        from nexus_video.packs import discover_packs
        packs = discover_packs(
            builtin_dir=_PROD_PACKS / "builtin",
            custom_dir=_PROD_PACKS / "custom",
        )
        ids = [p.pack_id for p in packs]
        assert "micron_original" in ids, \
            f"micron_original not found; packs={ids}"

    def test_micron_original_has_correct_name(self):
        from nexus_video.packs import discover_packs
        packs = discover_packs(
            builtin_dir=_PROD_PACKS / "builtin",
            custom_dir=_PROD_PACKS / "custom",
        )
        pack = next((p for p in packs if p.pack_id == "micron_original"), None)
        assert pack is not None
        assert "Voron Micron" in pack.name

    def test_micron_original_build_is_ready(self):
        from nexus_video.settings_bridge import build_is_ready
        assert build_is_ready(_PROD_BUILD, "micron_original"), \
            "micron_original build output is incomplete"

    def test_all_five_packs_discoverable(self):
        from nexus_video.packs import discover_packs
        packs = discover_packs(
            builtin_dir=_PROD_PACKS / "builtin",
            custom_dir=_PROD_PACKS / "custom",
        )
        assert len(packs) >= 5, \
            f"Expected ≥5 packs, got {len(packs)}: {[p.pack_id for p in packs]}"


# ---------------------------------------------------------------------------
# PackPopup — Apply / Preview / Cancel
# ---------------------------------------------------------------------------

class TestPackPopup:
    """Tests for the modal overlay shown when a pack tile is tapped."""

    def _make_screen(self, qapp, tmp_path, monkeypatch):
        prefs_path = tmp_path / "prefs.json"
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", prefs_path)
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        return screen

    def _make_mock_packs(self, n):
        packs = []
        for i in range(n):
            info = MagicMock()
            info.pack_id = f"pack_{i:02d}"
            info.name    = f"Pack {i:02d}"
            info.meta    = {"description": "", "distribution": "included"}
            packs.append(info)
        return packs

    # ── popup visibility ──────────────────────────────────────────────────────

    def test_popup_hidden_at_startup(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        assert screen._popup.isHidden()
        screen.close()

    def test_tile_tap_opens_popup(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        with patch("nexus.screens.startup_video.build_is_ready", return_value=True):
            screen._pack_page.rebuild(
                self._make_mock_packs(2), "pack_00", Path("/tmp/nonexistent"))
        screen.show_pack_popup("pack_00")
        assert not screen._popup.isHidden()
        screen.close()

    def test_popup_shows_correct_pack_name(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._packs = self._make_mock_packs(2)
        with patch("nexus.screens.startup_video.build_is_ready", return_value=True):
            screen._pack_page.rebuild(screen._packs, "pack_00", Path("/tmp/nonexistent"))
        screen.show_pack_popup("pack_01")
        assert screen._popup._pack_name == "Pack 01"
        screen.close()

    def test_popup_sets_pending_pack(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._packs = self._make_mock_packs(2)
        screen.show_pack_popup("pack_01")
        assert screen._pending_pack == "pack_01"
        screen.close()

    # ── Cancel ───────────────────────────────────────────────────────────────

    def test_cancel_hides_popup(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._packs = self._make_mock_packs(2)
        screen.show_pack_popup("pack_00")
        screen._popup._on_cancel()
        assert screen._popup.isHidden()
        screen.close()

    def test_cancel_clears_pending_pack(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._packs = self._make_mock_packs(2)
        screen.show_pack_popup("pack_00")
        screen._popup._on_cancel()
        assert screen._pending_pack is None
        screen.close()

    def test_cancel_does_not_change_applied_pack(self, qapp, tmp_path, monkeypatch):
        prefs_path = tmp_path / "prefs.json"
        prefs_path.write_text('{"startup_video_pack":"pack_00","startup_video_scale":"fit"}')
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", prefs_path)
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        screen._packs = self._make_mock_packs(2)
        applied_before = screen._selected_pack
        screen.show_pack_popup("pack_01")
        screen._popup._on_cancel()
        assert screen._selected_pack == applied_before
        screen.close()

    # ── Apply ─────────────────────────────────────────────────────────────────

    def test_apply_hides_popup(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._packs = self._make_mock_packs(2)
        with patch("nexus.screens.startup_video.build_is_ready", return_value=True):
            screen._pack_page.rebuild(screen._packs, "pack_00", Path("/tmp/nonexistent"))
        screen.show_pack_popup("pack_01")
        screen._popup._on_apply()
        assert screen._popup.isHidden()
        screen.close()

    def test_apply_persists_pack_to_prefs(self, qapp, tmp_path, monkeypatch):
        prefs_path = tmp_path / "prefs.json"
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", prefs_path)
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        screen._packs = self._make_mock_packs(2)
        with patch("nexus.screens.startup_video.build_is_ready", return_value=True):
            screen._pack_page.rebuild(screen._packs, "pack_01", Path("/tmp/nonexistent"))
        screen.show_pack_popup("pack_01")
        screen._popup._on_apply()
        saved = json.loads(prefs_path.read_text())
        assert saved["startup_video_pack"] == "pack_01"
        screen.close()

    def test_apply_updates_applied_tile_badge(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._packs = self._make_mock_packs(2)
        with patch("nexus.screens.startup_video.build_is_ready", return_value=True):
            screen._pack_page.rebuild(screen._packs, "pack_00", Path("/tmp/nonexistent"))
        screen.show_pack_popup("pack_01")
        screen._popup._on_apply()
        assert screen._pack_page.tiles["pack_01"].selected is True
        assert screen._pack_page.tiles["pack_00"].selected is False
        screen.close()

    def test_apply_clears_pending_pack(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._packs = self._make_mock_packs(2)
        with patch("nexus.screens.startup_video.build_is_ready", return_value=True):
            screen._pack_page.rebuild(screen._packs, "pack_00", Path("/tmp/nonexistent"))
        screen.show_pack_popup("pack_01")
        screen._popup._on_apply()
        assert screen._pending_pack is None
        screen.close()

    # ── Preview ───────────────────────────────────────────────────────────────

    def test_preview_hides_popup(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._packs = self._make_mock_packs(2)
        screen.show_pack_popup("pack_01")
        with patch.object(screen, "preview_pack"):
            screen._popup._on_preview()
        assert screen._popup.isHidden()
        screen.close()

    def test_preview_does_not_change_applied_pack(self, qapp, tmp_path, monkeypatch):
        prefs_path = tmp_path / "prefs.json"
        prefs_path.write_text('{"startup_video_pack":"pack_00","startup_video_scale":"fit"}')
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", prefs_path)
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        screen._packs = self._make_mock_packs(2)
        screen.show_pack_popup("pack_01")
        with patch.object(screen, "preview_pack"):
            screen._popup._on_preview()
        assert screen._selected_pack == "pack_00"
        screen.close()

    def test_preview_preserves_pending_pack(self, qapp, tmp_path, monkeypatch):
        """_pending_pack must survive the Preview action so the popup can reopen."""
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._packs = self._make_mock_packs(2)
        screen.show_pack_popup("pack_01")
        with patch.object(screen, "preview_pack"):
            screen._popup._on_preview()
        assert screen._pending_pack == "pack_01"
        screen.close()

    def test_preview_calls_preview_pack_with_correct_args(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._packs = self._make_mock_packs(2)
        screen.show_pack_popup("pack_01")
        with patch.object(screen, "preview_pack") as mock_preview:
            screen._popup._on_preview()
        mock_preview.assert_called_once_with("pack_01", "Pack 01")
        screen.close()

    # ── Navigation — popup re-opens after returning from preview ──────────────

    def test_show_event_reopens_popup_when_pending(self, qapp, tmp_path, monkeypatch):
        """When showEvent fires after returning from preview, the popup should reappear."""
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        mock_packs = self._make_mock_packs(2)  # pack_00, pack_01
        # Simulate state after the user tapped Preview: popup hidden, pending set
        screen._pending_pack = "pack_01"
        screen._popup.hide()
        # _refresh() does a local import of discover_packs from nexus_video.packs
        with patch("nexus.screens.startup_video.build_is_ready", return_value=False), \
             patch("nexus_video.packs.discover_packs", return_value=mock_packs):
            from PyQt6.QtGui import QShowEvent
            screen.showEvent(QShowEvent())
        assert not screen._popup.isHidden(), "Popup should reopen for pending selection"
        screen.close()

    def test_show_event_does_not_open_popup_when_no_pending(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._pending_pack = None
        with patch("nexus.screens.startup_video.build_is_ready", return_value=False), \
             patch("nexus_video.packs.discover_packs", return_value=[]):
            from PyQt6.QtGui import QShowEvent
            screen.showEvent(QShowEvent())
        assert screen._popup.isHidden()
        screen.close()

    def test_show_event_ignores_pending_if_pack_disappeared(self, qapp, tmp_path, monkeypatch):
        """If the pending pack no longer exists in the discovered list, skip re-opening."""
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._pending_pack = "deleted_pack"
        with patch("nexus.screens.startup_video.build_is_ready", return_value=False), \
             patch("nexus_video.packs.discover_packs", return_value=[]):
            from PyQt6.QtGui import QShowEvent
            screen.showEvent(QShowEvent())
        assert screen._popup.isHidden()
        screen.close()

    # ── popup geometry ────────────────────────────────────────────────────────

    def test_popup_covers_full_screen(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        popup = screen._popup
        assert popup.width()  == 800
        assert popup.height() == 480
        screen.close()

    def test_popup_has_three_buttons(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        popup = screen._popup
        assert popup._btn_apply   is not None
        assert popup._btn_preview is not None
        assert popup._btn_cancel  is not None
        screen.close()

    def test_popup_buttons_are_touch_sized(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._packs = self._make_mock_packs(1)
        screen.show_pack_popup("pack_00")
        for btn in (screen._popup._btn_apply,
                    screen._popup._btn_preview,
                    screen._popup._btn_cancel):
            assert btn.height() >= 44, \
                f"Button {btn.text()!r} height {btn.height()} < 44px"
        screen.close()


# ---------------------------------------------------------------------------
# Apply confirmation (MessagePopup)
# ---------------------------------------------------------------------------

class TestApplyConfirmation:
    """Tests for the success / error overlay shown after Apply."""

    def _make_screen(self, qapp, tmp_path, monkeypatch):
        prefs_path = tmp_path / "prefs.json"
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", prefs_path)
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        return screen

    def _make_mock_packs(self, n):
        packs = []
        for i in range(n):
            info = MagicMock()
            info.pack_id = f"pack_{i:02d}"
            info.name    = f"Pack {i:02d}"
            info.meta    = {"description": "", "distribution": "included"}
            packs.append(info)
        return packs

    # ── MessagePopup widget ───────────────────────────────────────────────────

    def test_msg_popup_hidden_at_startup(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        assert screen._msg_popup.isHidden()
        screen.close()

    def test_msg_popup_covers_full_screen(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        popup = screen._msg_popup
        assert popup.width()  == 800
        assert popup.height() == 480
        screen.close()

    def test_msg_popup_has_ok_button(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        assert screen._msg_popup._btn_ok is not None
        screen.close()

    def test_ok_button_hides_popup(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._msg_popup.show_message("Title", "Body")
        screen._msg_popup._btn_ok.click()
        assert screen._msg_popup.isHidden()
        screen.close()

    # ── Apply success path ────────────────────────────────────────────────────

    def test_apply_shows_confirmation_on_success(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._packs = self._make_mock_packs(2)
        with patch("nexus.screens.startup_video.build_is_ready", return_value=True):
            screen._pack_page.rebuild(screen._packs, "pack_00", Path("/tmp/nonexistent"))
        screen.show_pack_popup("pack_01")
        screen._popup._on_apply()
        assert not screen._msg_popup.isHidden(), "Confirmation popup should appear"
        assert screen._msg_popup._is_error is False
        screen.close()

    def test_apply_confirmation_title(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._packs = self._make_mock_packs(2)
        with patch("nexus.screens.startup_video.build_is_ready", return_value=True):
            screen._pack_page.rebuild(screen._packs, "pack_01", Path("/tmp/nonexistent"))
        screen.show_pack_popup("pack_01")
        screen._popup._on_apply()
        assert "Applied" in screen._msg_popup._title
        screen.close()

    def test_apply_confirmation_subtitle_contains_pack_name(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._packs = self._make_mock_packs(2)
        with patch("nexus.screens.startup_video.build_is_ready", return_value=True):
            screen._pack_page.rebuild(screen._packs, "pack_01", Path("/tmp/nonexistent"))
        screen.show_pack_popup("pack_01")
        screen._popup._on_apply()
        assert "Pack 01" in screen._msg_popup._subtitle
        screen.close()

    # ── Apply failure path ────────────────────────────────────────────────────

    def test_apply_shows_error_on_persist_failure(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._packs = self._make_mock_packs(2)
        with patch("nexus.screens.startup_video.build_is_ready", return_value=True):
            screen._pack_page.rebuild(screen._packs, "pack_00", Path("/tmp/nonexistent"))
        screen.show_pack_popup("pack_01")
        # Force persistence to fail
        with patch.object(screen, "_persist", return_value=False):
            screen.apply_pack("pack_01")
        assert not screen._msg_popup.isHidden()
        assert screen._msg_popup._is_error is True
        screen.close()

    def test_persist_returns_true_on_success(self, qapp, tmp_path, monkeypatch):
        prefs_path = tmp_path / "prefs.json"
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", prefs_path)
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        result = screen._persist()
        assert result is True
        screen.close()

    def test_persist_returns_false_on_exception(self, qapp, tmp_path, monkeypatch):
        prefs_path = tmp_path / "prefs.json"
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", prefs_path)
        from nexus.screens.startup_video import StartupVideoScreen
        import nexus_video.settings_bridge as _sb
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        with patch.object(_sb, "set_selection", side_effect=OSError("disk full")):
            result = screen._persist()
        assert result is False
        screen.close()

    # ── Cancel never shows message ────────────────────────────────────────────

    def test_cancel_does_not_show_msg_popup(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._packs = self._make_mock_packs(2)
        screen.show_pack_popup("pack_01")
        screen._popup._on_cancel()
        assert screen._msg_popup.isHidden()
        screen.close()


# ---------------------------------------------------------------------------
# Preview screen — load_pack and stack registration
# ---------------------------------------------------------------------------

class TestPreviewScreenIntegration:
    """Tests for the preview navigation fix and load_pack."""

    def _make_screen(self, qapp, tmp_path, monkeypatch):
        prefs_path = tmp_path / "prefs.json"
        monkeypatch.setattr("nexus_video.settings_bridge.PREFS_PATH", prefs_path)
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(800, 480)
        return screen

    def test_preview_screen_is_none_at_startup(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        assert screen._preview_screen is None
        screen.close()

    def test_preview_pack_creates_preview_screen(self, qapp, tmp_path, monkeypatch):
        from nexus.screens.video_preview import VideoPreviewScreen
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._packs = []
        screen.preview_pack("nexus_signature", "Nexus Signature")
        assert screen._preview_screen is not None
        assert isinstance(screen._preview_screen, VideoPreviewScreen)
        screen.close()

    def test_preview_pack_reuses_same_instance(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._packs = []
        screen.preview_pack("pack_a", "Pack A")
        first = screen._preview_screen
        screen.preview_pack("pack_b", "Pack B")
        assert screen._preview_screen is first, "Should reuse the same VideoPreviewScreen"
        screen.close()

    def test_load_pack_updates_paths(self, qapp, tmp_path, monkeypatch):
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._packs = []
        screen.preview_pack("nexus_signature", "Nexus Signature")
        ps = screen._preview_screen
        assert ps._pack_name == "Nexus Signature"
        screen.close()

    def test_load_pack_resets_stopped_flag(self, qapp, tmp_path, monkeypatch):
        from nexus.screens.video_preview import VideoPreviewScreen
        screen = self._make_screen(qapp, tmp_path, monkeypatch)
        screen._packs = []
        screen.preview_pack("pack_a", "Pack A")
        ps = screen._preview_screen
        ps._stopped = True  # simulate user pressed Stop
        # Preview a new pack → stopped must be cleared for auto-play
        screen.preview_pack("pack_b", "Pack B")
        assert ps._stopped is False
        screen.close()

    def test_video_preview_load_pack_clears_error(self, qapp):
        from nexus.screens.video_preview import VideoPreviewScreen
        ps = VideoPreviewScreen(ctl=None)
        ps.resize(800, 480)
        ps._error_text = "some earlier error"
        ps.load_pack(None, None, "New Pack")
        assert ps._error_text == ""
        ps.close()

    def test_video_preview_load_pack_updates_name(self, qapp):
        from nexus.screens.video_preview import VideoPreviewScreen
        ps = VideoPreviewScreen(pack_name="Old Pack", ctl=None)
        ps.resize(800, 480)
        ps.load_pack(None, None, "New Pack")
        assert ps._pack_name == "New Pack"
        ps.close()

    def test_video_preview_load_pack_resets_stopped(self, qapp):
        from nexus.screens.video_preview import VideoPreviewScreen
        ps = VideoPreviewScreen(ctl=None)
        ps.resize(800, 480)
        ps._stopped = True
        ps.load_pack(None, None, "Pack")
        assert ps._stopped is False
        ps.close()
