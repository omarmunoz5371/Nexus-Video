"""Settings UI layout validation (Task 4 — 3×3 grid, touch targets, bounds).

Verifies:
- All 9 Settings tiles exist and are within the 800×480 viewport
- Touch targets are at least 44×44 px (HIG minimum)
- Startup Video submenu back navigation present
- 3×3 grid layout integrity
"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_dev_root = Path(__file__).resolve().parent.parent / "nexus-screen-dev"
if str(_dev_root) not in sys.path:
    sys.path.insert(0, str(_dev_root))

from PyQt6.QtWidgets import QApplication

_qapp = QApplication.instance() or QApplication(sys.argv)

SCREEN_W, SCREEN_H = 800, 480
MIN_TOUCH = 44  # HIG minimum touch target px


# ---------------------------------------------------------------------------
# Settings tile layout
# ---------------------------------------------------------------------------

class TestSettingsTileLayout:
    def _make_settings(self):
        from nexus.screens.settings import SettingsPage
        page = SettingsPage()
        page.resize(SCREEN_W, SCREEN_H)
        return page

    def test_exactly_nine_settings_tiles(self):
        from nexus.screens.settings import SETTINGS
        assert len(SETTINGS) == 9

    def test_startup_video_in_settings(self):
        from nexus.screens.settings import SETTINGS
        keys = [s[0] for s in SETTINGS]
        assert "startup_video" in keys

    def test_all_tiles_within_screen_bounds(self):
        page = self._make_settings()
        for key, tile in page.tiles.items():
            g = tile.geometry()
            assert g.left()   >= 0,      f"{key} left={g.left()} < 0"
            assert g.top()    >= 0,      f"{key} top={g.top()} < 0"
            assert g.right()  <= SCREEN_W, f"{key} right={g.right()} > {SCREEN_W}"
            assert g.bottom() <= SCREEN_H, f"{key} bottom={g.bottom()} > {SCREEN_H}"

    def test_all_tiles_meet_touch_target_minimum(self):
        page = self._make_settings()
        for key, tile in page.tiles.items():
            g = tile.geometry()
            assert g.width()  >= MIN_TOUCH, \
                f"{key} width={g.width()} < {MIN_TOUCH}px touch minimum"
            assert g.height() >= MIN_TOUCH, \
                f"{key} height={g.height()} < {MIN_TOUCH}px touch minimum"

    def test_settings_tiles_arranged_in_3_columns(self):
        """The 9 primary SETTINGS tiles must be in exactly 3 column positions."""
        from nexus.screens.settings import SETTINGS
        page = self._make_settings()
        setting_keys = {s[0] for s in SETTINGS}
        x_positions = sorted(set(
            page.tiles[k].geometry().x()
            for k in setting_keys if k in page.tiles
        ))
        assert len(x_positions) == 3, \
            f"Expected 3 column positions for SETTINGS, found {len(x_positions)}: {x_positions}"

    def test_tiles_do_not_visually_overlap(self):
        """Adjacent tiles share a 1-pixel border in Qt; shrink by 1px before checking."""
        page = self._make_settings()
        tiles = list(page.tiles.values())
        for i, a in enumerate(tiles):
            for b in tiles[i + 1:]:
                # adjust(0,0,-1,-1) shrinks right/bottom by 1px so shared borders are excluded
                ga = a.geometry().adjusted(0, 0, -1, -1)
                gb = b.geometry().adjusted(0, 0, -1, -1)
                assert not ga.intersects(gb), \
                    f"Tiles overlap: {a.objectName()} and {b.objectName()}"

    def test_startup_video_tile_accessible(self):
        page = self._make_settings()
        tile = page.tiles.get("startup_video")
        assert tile is not None
        g = tile.geometry()
        assert g.width()  >= MIN_TOUCH
        assert g.height() >= MIN_TOUCH


# ---------------------------------------------------------------------------
# StartupVideoScreen layout
# ---------------------------------------------------------------------------

class TestStartupVideoScreenLayout:
    def test_tab_list_within_bounds(self):
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(SCREEN_W, SCREEN_H)
        g = screen._tabs.geometry()
        assert g.left()   >= 0
        assert g.right()  <= SCREEN_W
        assert g.bottom() <= SCREEN_H

    def test_pack_page_within_bounds(self):
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(SCREEN_W, SCREEN_H)
        g = screen._pack_page.geometry()
        assert g.right()  <= SCREEN_W
        assert g.bottom() <= SCREEN_H
        screen.close()

    def test_scale_page_within_bounds(self):
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(SCREEN_W, SCREEN_H)
        g = screen._scale_page.geometry()
        assert g.right()  <= SCREEN_W
        assert g.bottom() <= SCREEN_H
        screen.close()

    def test_status_page_within_bounds(self):
        from nexus.screens.startup_video import StartupVideoScreen
        screen = StartupVideoScreen(ctl=None)
        screen.resize(SCREEN_W, SCREEN_H)
        g = screen._status_page.geometry()
        assert g.right()  <= SCREEN_W
        assert g.bottom() <= SCREEN_H
        screen.close()


# ---------------------------------------------------------------------------
# VideoPreviewScreen layout
# ---------------------------------------------------------------------------

class TestVideoPreviewLayout:
    def test_canvas_within_bounds(self):
        from nexus.screens.video_preview import VideoPreviewScreen, PREV_W, PREV_H
        screen = VideoPreviewScreen(None, None, "Test", ctl=None)
        screen.resize(SCREEN_W, SCREEN_H)
        g = screen._canvas.geometry()
        assert g.right()  <= SCREEN_W, f"Canvas right={g.right()} > {SCREEN_W}"
        assert g.bottom() <= SCREEN_H, f"Canvas bottom={g.bottom()} > {SCREEN_H}"
        screen.close()

    def test_control_buttons_within_bounds(self):
        from nexus.screens.video_preview import VideoPreviewScreen
        screen = VideoPreviewScreen(None, None, "Test", ctl=None)
        screen.resize(SCREEN_W, SCREEN_H)
        for btn in (screen._btn_play, screen._btn_stop, screen._btn_back):
            g = btn.geometry()
            assert g.right()  <= SCREEN_W, f"Button right={g.right()} > {SCREEN_W}"
            assert g.bottom() <= SCREEN_H, f"Button bottom={g.bottom()} > {SCREEN_H}"
        screen.close()

    def test_control_buttons_meet_touch_target(self):
        from nexus.screens.video_preview import VideoPreviewScreen
        screen = VideoPreviewScreen(None, None, "Test", ctl=None)
        screen.resize(SCREEN_W, SCREEN_H)
        for btn in (screen._btn_play, screen._btn_stop, screen._btn_back):
            g = btn.geometry()
            assert g.width()  >= MIN_TOUCH
            assert g.height() >= MIN_TOUCH
        screen.close()
