"""Tests for the VideoPreviewScreen (Task 1 — animated in-app preview).

Runs headless with QT_QPA_PLATFORM=offscreen.
QProcess is mocked throughout so no real ffmpeg is started.
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

_dev_root = Path(__file__).resolve().parent.parent / "nexus-screen-dev"
if str(_dev_root) not in sys.path:
    sys.path.insert(0, str(_dev_root))


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_screen(tmp_path, intro=True, loop=True, name="TestPack", qapp=None):
    from nexus.screens.video_preview import VideoPreviewScreen, PREV_W, PREV_H
    intro_p = tmp_path / "intro.mp4" if intro else None
    loop_p  = tmp_path / "loop.mp4"  if loop  else None
    if intro and intro_p:
        intro_p.write_bytes(b"\x00" * 16)
    if loop and loop_p:
        loop_p.write_bytes(b"\x00" * 16)
    s = VideoPreviewScreen(intro_p, loop_p, name, ctl=None)
    s.resize(800, 480)
    return s


# ---------------------------------------------------------------------------
# Basic instantiation
# ---------------------------------------------------------------------------

class TestVideoPreviewInstantiation:
    def test_screen_instantiates(self, qapp, tmp_path):
        s = _make_screen(tmp_path)
        assert s is not None
        s.close()

    def test_title_is_video_preview(self, qapp, tmp_path):
        s = _make_screen(tmp_path)
        assert s.TITLE == "Video Preview"
        s.close()

    def test_is_submenu(self, qapp, tmp_path):
        s = _make_screen(tmp_path)
        assert s.submenu is True
        assert s.fullscreen is True
        s.close()

    def test_canvas_has_correct_size(self, qapp, tmp_path):
        from nexus.screens.video_preview import PREV_W, PREV_H
        s = _make_screen(tmp_path)
        s.resize(800, 480)
        assert s._canvas.width()  == PREV_W
        assert s._canvas.height() == PREV_H
        s.close()

    def test_three_control_buttons_exist(self, qapp, tmp_path):
        s = _make_screen(tmp_path)
        assert s._btn_play is not None
        assert s._btn_stop is not None
        assert s._btn_back is not None
        s.close()


# ---------------------------------------------------------------------------
# Button state management
# ---------------------------------------------------------------------------

class TestButtonStates:
    def test_play_enabled_stop_disabled_initially(self, qapp, tmp_path):
        s = _make_screen(tmp_path)
        assert s._btn_play.isEnabled() is True
        assert s._btn_stop.isEnabled() is False
        s.close()

    def test_play_disables_when_playing(self, qapp, tmp_path):
        s = _make_screen(tmp_path)
        with patch.object(s, '_launch'):
            s._on_play()
        assert s._btn_play.isEnabled() is False
        assert s._btn_stop.isEnabled() is True
        s.close()

    def test_stop_re_enables_play(self, qapp, tmp_path):
        s = _make_screen(tmp_path)
        with patch.object(s, '_launch'):
            s._on_play()
        s._on_stop()
        assert s._btn_play.isEnabled() is True
        assert s._btn_stop.isEnabled() is False
        s.close()


# ---------------------------------------------------------------------------
# Missing file handling
# ---------------------------------------------------------------------------

class TestMissingFiles:
    def test_missing_intro_shows_error(self, qapp, tmp_path):
        s = _make_screen(tmp_path, intro=False)
        s._on_play()
        assert s._error_text != ""
        assert "intro.mp4" in s._error_text
        s.close()

    def test_missing_loop_shows_error(self, qapp, tmp_path):
        s = _make_screen(tmp_path, loop=False)
        # Simulate intro finishing: proc exits 0, so code tries to start loop
        s._playing_loop = False
        s._stopped = False
        s._on_proc_finished(0, None)  # intro "finished" → triggers _start_loop()
        # _start_loop sees loop_p=None → shows error
        assert s._error_text != ""
        assert "loop.mp4" in s._error_text
        s.close()

    def test_error_state_re_enables_play(self, qapp, tmp_path):
        s = _make_screen(tmp_path, intro=False)
        s._on_play()
        assert s._btn_play.isEnabled() is True
        s.close()

    def test_missing_intro_path_none(self, qapp, tmp_path):
        from nexus.screens.video_preview import VideoPreviewScreen
        s = VideoPreviewScreen(None, None, "NoPack", ctl=None)
        s.resize(800, 480)
        s._on_play()
        assert s._error_text != ""
        s.close()


# ---------------------------------------------------------------------------
# Stop and cleanup
# ---------------------------------------------------------------------------

class TestStopAndCleanup:
    def test_stop_kills_process(self, qapp, tmp_path):
        s = _make_screen(tmp_path)
        mock_proc = MagicMock()
        from PyQt6.QtCore import QProcess
        mock_proc.state.return_value = QProcess.ProcessState.Running
        s._proc = mock_proc
        s._on_stop()
        mock_proc.kill.assert_called_once()
        s.close()

    def test_hide_kills_process(self, qapp, tmp_path):
        s = _make_screen(tmp_path)
        s.show()
        qapp.processEvents()
        # Replace the auto-started proc with a mock
        s._kill_proc()  # stop auto-play proc
        mock_proc = MagicMock()
        from PyQt6.QtCore import QProcess
        mock_proc.state.return_value = QProcess.ProcessState.Running
        s._proc = mock_proc
        s.hide()
        mock_proc.kill.assert_called_once()
        s.close()

    def test_stopped_flag_set_on_stop(self, qapp, tmp_path):
        s = _make_screen(tmp_path)
        s._on_stop()
        assert s._stopped is True
        s.close()


# ---------------------------------------------------------------------------
# Frame handling
# ---------------------------------------------------------------------------

class TestFrameHandling:
    def test_incomplete_buffer_does_not_render(self, qapp, tmp_path):
        from nexus.screens.video_preview import FRAME_BYTES
        from PyQt6.QtCore import QByteArray
        s = _make_screen(tmp_path)
        s._buf = QByteArray(b"\x00" * (FRAME_BYTES - 1))
        s._frame_count = 0
        s._on_frame_tick()
        assert s._frame_count == 0  # no frame was consumed
        s.close()

    def test_complete_frame_increments_counter(self, qapp, tmp_path):
        from nexus.screens.video_preview import FRAME_BYTES
        from PyQt6.QtCore import QByteArray
        s = _make_screen(tmp_path)
        s._buf = QByteArray(b"\x00" * FRAME_BYTES)
        s._on_frame_tick()
        assert s._frame_count == 1
        s.close()

    def test_complete_frame_consumes_exactly_one_frame(self, qapp, tmp_path):
        from nexus.screens.video_preview import FRAME_BYTES
        from PyQt6.QtCore import QByteArray
        s = _make_screen(tmp_path)
        extra = b"\xFF" * 10
        s._buf = QByteArray(b"\x00" * FRAME_BYTES + extra)
        s._on_frame_tick()
        assert len(s._buf) == len(extra)
        s.close()


# ---------------------------------------------------------------------------
# Proc finished transitions
# ---------------------------------------------------------------------------

class TestProcTransitions:
    def test_intro_success_starts_loop(self, qapp, tmp_path):
        s = _make_screen(tmp_path)
        s._playing_loop = False
        s._frame_count = 10  # simulate frames were shown
        with patch.object(s, '_start_loop') as mock_loop:
            s._on_proc_finished(0, None)
        mock_loop.assert_called_once()
        s.close()

    def test_intro_zero_frames_shows_error(self, qapp, tmp_path):
        s = _make_screen(tmp_path)
        s._playing_loop = False
        s._frame_count = 0
        s._on_proc_finished(1, None)
        assert s._error_text != ""
        s.close()

    def test_stopped_flag_suppresses_transition(self, qapp, tmp_path):
        s = _make_screen(tmp_path)
        s._stopped = True
        s._frame_count = 10
        with patch.object(s, '_start_loop') as mock_loop:
            s._on_proc_finished(0, None)
        mock_loop.assert_not_called()
        s.close()


# ---------------------------------------------------------------------------
# Back button
# ---------------------------------------------------------------------------

class TestBackButton:
    def test_back_calls_ctl_back(self, qapp, tmp_path):
        from nexus.screens.video_preview import VideoPreviewScreen
        intro_p = tmp_path / "intro.mp4"
        intro_p.write_bytes(b"\x00" * 16)
        loop_p = tmp_path / "loop.mp4"
        loop_p.write_bytes(b"\x00" * 16)
        ctl = MagicMock()
        s = VideoPreviewScreen(intro_p, loop_p, "Test", ctl=ctl)
        s.resize(800, 480)
        s._on_back()
        ctl.back.assert_called_once()
        s.close()

    def test_back_stops_playback(self, qapp, tmp_path):
        s = _make_screen(tmp_path)
        with patch.object(s, '_kill_proc') as mock_kill:
            s._on_back()
        mock_kill.assert_called_once()
        s.close()
