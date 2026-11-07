#!/usr/bin/env python3
"""Nexus Video boot player: plays the selected pack intro once, then loops until Nexus Screen takes over.

Reads config.json to determine the active pack. Falls back to nexus_signature if config is missing
or the specified pack is not built. Compatible with the existing nexus-splash handover protocol:
  /run/nexus-splash/player.pid   — written at start
  /run/nexus-splash/ready        — created by Nexus Screen when it is ready to show
  /run/nexus-splash/released     — created here after yielding; Nexus Screen then shows its window

This player is a drop-in replacement for nexus-screen/splash/player.py for use with nexus-video.service.
"""
import argparse
import ctypes
import fcntl
import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

KDSETMODE, KD_GRAPHICS = 0x4B3A, 1
PR_CAP_AMBIENT, PR_CAP_AMBIENT_CLEAR_ALL = 47, 4
T0 = time.monotonic()

DEFAULT_PACK   = "nexus_signature"
DEFAULT_SCALE  = "fit"
MIN_W, MIN_H   = 480, 320  # minimum supported display resolution


def drop_capabilities():
    try:
        ctypes.CDLL(None, use_errno=True).prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_CLEAR_ALL, 0, 0, 0)
    except (OSError, AttributeError):
        pass


def log(msg):
    print(f"nexus-video: {time.monotonic() - T0:6.2f}s {msg}", flush=True)


def wait_for_device(path, seconds):
    end = time.monotonic() + seconds
    while not os.path.exists(path):
        if time.monotonic() >= end:
            return False
        time.sleep(0.05)
    return True


def other_holders(path):
    target, me, found = os.path.realpath(path), os.getpid(), []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        if int(pid) == me:
            continue
        try:
            fds = os.listdir(f"/proc/{pid}/fd")
        except OSError:
            continue
        for fd in fds:
            try:
                if os.path.realpath(f"/proc/{pid}/fd/{fd}") == target:
                    found.append(int(pid))
                    break
            except OSError:
                pass
    return found


def read_config(config_path: str) -> dict:
    try:
        with open(config_path) as fh:
            cfg = json.load(fh)
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


def resolve_pack(build_dir: str, config: dict) -> tuple[str, str, str, str]:
    """Return (intro_path, loop_path, still_path, pack_id) for the configured pack.

    Falls back to nexus_signature if the configured pack's build output is incomplete.
    """
    bd = Path(build_dir)
    pack_id = config.get("pack", DEFAULT_PACK)

    def _paths(pid):
        d = bd / pid
        return str(d / "intro.mp4"), str(d / "loop.mp4"), str(d / "still.rgb565")

    def _ready(pid):
        d = bd / pid
        return all((d / f).exists() for f in ("intro.mp4", "loop.mp4", "still.rgb565"))

    if _ready(pack_id):
        intro, loop, still = _paths(pack_id)
        return intro, loop, still, pack_id

    log(f"pack '{pack_id}' not built — falling back to {DEFAULT_PACK}")
    if _ready(DEFAULT_PACK):
        intro, loop, still = _paths(DEFAULT_PACK)
        return intro, loop, still, DEFAULT_PACK

    # Last resort: any ready pack
    try:
        for d in sorted((bd).iterdir()):
            if _ready(d.name):
                log(f"using fallback pack: {d.name}")
                intro, loop, still = _paths(d.name)
                return intro, loop, still, d.name
    except OSError:
        pass

    # Nothing ready
    return "", "", "", ""


class Framebuffer:
    # FFmpeg pix_fmt name keyed by (bpp, r_off, r_len, g_off, g_len, b_off, b_len).
    _FMT_MAP = {
        (16, 11, 5,  5, 6,  0, 5): "rgb565le",
        (32,  8, 8, 16, 8, 24, 8): "bgra",
        (32,  0, 8,  8, 8, 16, 8): "rgba",
        (32, 16, 8,  8, 8,  0, 8): "argb",
        (32, 24, 8, 16, 8,  8, 8): "abgr",
    }

    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR)
        # Sensible defaults for non-sysfs paths (unit tests, pipes).
        self.w, self.h, self.bpp = 800, 480, 16
        self.bytes_pp = 2
        self.stride = self.w * self.bytes_pp
        self.pix_fmt = "rgb565le"
        if path.startswith("/dev/fb"):
            sysfs = "/sys/class/graphics/" + os.path.basename(path)
            size_str = open(sysfs + "/virtual_size").read().strip()
            self.w, self.h = map(int, size_str.split(","))
            self.bpp = int(open(sysfs + "/bits_per_pixel").read())
            self.bytes_pp = self.bpp // 8
            if self.w < MIN_W or self.h < MIN_H:
                raise SystemExit(
                    f"nexus-video: display {self.w}×{self.h} is below the minimum "
                    f"{MIN_W}×{MIN_H} — not drawing"
                )
            fmt = self._detect_format(sysfs)
            if fmt is None:
                raise SystemExit(
                    f"nexus-video: {path} pixel format ({self.bpp}bpp) is not supported. "
                    f"Supported: RGB565 (16bpp), BGRA8888/RGBA8888/ARGB8888/ABGR8888 (32bpp)"
                )
            self.pix_fmt = fmt
            self.stride = int(open(sysfs + "/stride").read())

    @staticmethod
    def _read_channel(sysfs, name):
        try:
            parts = open(f"{sysfs}/{name}").read().strip().split(",")
            return int(parts[0]), int(parts[1])  # offset, length
        except (OSError, ValueError, IndexError):
            return -1, 0

    def _detect_format(self, sysfs):
        r_off, r_len = self._read_channel(sysfs, "red")
        g_off, g_len = self._read_channel(sysfs, "green")
        b_off, b_len = self._read_channel(sysfs, "blue")
        return self._FMT_MAP.get((self.bpp, r_off, r_len, g_off, g_len, b_off, b_len))

    def frame_size(self):
        return self.w * self.h * self.bytes_pp

    def show(self, frame):
        bpl = self.w * self.bytes_pp
        if self.stride == bpl:
            os.pwrite(self.fd, frame, 0)
        else:
            for y in range(self.h):
                os.pwrite(self.fd, frame[y * bpl:(y + 1) * bpl], y * self.stride)


class Player:
    def __init__(self, args, scale=DEFAULT_SCALE):
        self.args = args
        self.scale = scale if scale in ("fit", "fill", "stretch") else DEFAULT_SCALE
        self.fb = Framebuffer(args.fb)
        self.run = args.run_dir
        self.deadline = T0 + args.max_seconds
        self.stop_reason = None
        self.frames = 0
        self._graphics_at = 0.0
        self._graphics_failed = False
        signal.signal(signal.SIGTERM, lambda *_: self._stop("SIGTERM"))
        signal.signal(signal.SIGINT,  lambda *_: self._stop("SIGINT"))

    def _stop(self, why):
        self.stop_reason = self.stop_reason or why

    def graphics_mode(self):
        if not self.args.tty or time.monotonic() - self._graphics_at < 0.5:
            return
        self._graphics_at = time.monotonic()
        try:
            fd = os.open(self.args.tty, os.O_WRONLY | os.O_NOCTTY)
            try:
                fcntl.ioctl(fd, KDSETMODE, KD_GRAPHICS)
            finally:
                os.close(fd)
        except OSError as e:
            if not self._graphics_failed:
                self._graphics_failed = True
                log(f"console graphics mode not set ({e}); continuing")

    def should_stop(self):
        if self.stop_reason is None:
            if os.path.exists(os.path.join(self.run, "ready")):
                self.stop_reason = "Nexus Screen ready"
            elif time.monotonic() >= self.deadline:
                self.stop_reason = f"time limit {self.args.max_seconds}s"
        return self.stop_reason is not None

    def _vf_filter(self):
        W, H = self.fb.w, self.fb.h
        if self.scale == "fill":
            return f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
        if self.scale == "stretch":
            return f"scale={W}:{H}"
        # fit (default) — letterbox with black bars
        return (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black")

    def _read_frame(self, fd):
        frame_size = self.fb.frame_size()
        buf = bytearray()
        while len(buf) < frame_size:
            if self.should_stop():
                return b""
            if not select.select([fd], [], [], 0.05)[0]:
                continue
            chunk = os.read(fd, frame_size - len(buf))
            if not chunk:
                return None
            buf += chunk
        return bytes(buf)

    def _wait_until(self, t):
        while not self.should_stop() and time.monotonic() < t:
            time.sleep(min(0.05, max(0.0, t - time.monotonic())))

    def play(self, path, loop=False):
        if not path or not os.path.exists(path):
            log(f"media not found: {path!r}")
            return False
        cmd = (["ffmpeg", "-nostdin", "-v", "error", "-threads", "2"]
               + (["-stream_loop", "-1"] if loop else [])
               + ["-i", path, "-an", "-vf", self._vf_filter(),
                  "-f", "rawvideo", "-pix_fmt", self.fb.pix_fmt, "-"])
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    bufsize=0, preexec_fn=drop_capabilities)
        except OSError as e:
            log(f"cannot start ffmpeg: {e}")
            return False
        shown, period, base = 0, 1.0 / self.args.fps, None
        try:
            while True:
                frame = self._read_frame(proc.stdout.fileno())
                if not frame:
                    break
                if base is None or time.monotonic() - (base + shown * period) > 0.5:
                    base = time.monotonic() - shown * period
                self._wait_until(base + shown * period)
                if self.should_stop():
                    break
                self.fb.show(frame)
                shown += 1
                self.graphics_mode()
        finally:
            proc.stdout.close()
            proc.kill()
            proc.wait()
            err = proc.stderr.read().decode(errors="replace").strip()
        self.frames += shown
        log(f"{os.path.basename(path)}: {shown} frames"
            + (f" ({err.splitlines()[-1]})" if err and not shown else ""))
        return shown > 0

    def _convert_still(self, png_path):
        """Convert still.png to raw pixels at the display's resolution and format."""
        cmd = ["ffmpeg", "-nostdin", "-v", "error",
               "-i", png_path, "-vf", self._vf_filter(),
               "-f", "rawvideo", "-pix_fmt", self.fb.pix_fmt,
               "-frames:v", "1", "-"]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=10,
                                    preexec_fn=drop_capabilities)
            if result.returncode == 0 and len(result.stdout) == self.fb.frame_size():
                log(f"still: converted {os.path.basename(png_path)} → "
                    f"{self.fb.w}×{self.fb.h} {self.fb.pix_fmt}")
                return bytes(result.stdout)
            log(f"still: PNG conversion failed (ret={result.returncode})")
        except (OSError, subprocess.TimeoutExpired) as e:
            log(f"still: PNG conversion error: {e}")
        return b""

    def _load_still(self, still_path):
        """Load the still frame, falling back to PNG conversion if size mismatches."""
        if not still_path:
            return b""
        frame_size = self.fb.frame_size()
        try:
            raw = open(still_path, "rb").read()
        except OSError as e:
            log(f"still frame unavailable: {e}")
            return b""
        if len(raw) == frame_size:
            return raw
        # Size mismatch (display resolution differs from build resolution).
        # Try a companion .png at the same path (e.g. still.png alongside still.rgb565).
        png_path = str(still_path).rsplit(".", 1)[0] + ".png"
        if os.path.exists(png_path):
            converted = self._convert_still(png_path)
            if converted:
                return converted
        log(f"still: {len(raw)} bytes does not match display frame {frame_size} bytes — skipping")
        return b""

    def hold_still(self, still_path):
        frame = self._load_still(still_path)
        if frame:
            self.fb.show(frame)
            log("holding the still frame")
        while not self.should_stop():
            self.graphics_mode()
            if frame:
                self.fb.show(frame)
            time.sleep(0.1)

    def main(self, intro, loop, still):
        os.makedirs(self.run, exist_ok=True)
        for name in ("ready", "released"):
            try:
                os.remove(os.path.join(self.run, name))
            except FileNotFoundError:
                pass
        with open(os.path.join(self.run, "player.pid"), "w") as fh:
            fh.write(str(os.getpid()))
        self.graphics_mode()
        played = self.play(intro)
        if not self.should_stop():
            if not self.play(loop, loop=True) and not self.should_stop():
                self.hold_still(still)
        elif not played:
            self.hold_still(still)
        open(os.path.join(self.run, "released"), "w").close()
        log(f"stopped: {self.stop_reason or 'end'} — {self.frames} frames shown, screen released")
        return 0


def parse(argv=None):
    _home = Path.home()
    _nv   = _home / "nexus-video"
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config",       default=str(_nv / "config.json"))
    ap.add_argument("--build-dir",    default=str(_nv / "build"))
    ap.add_argument("--fb",           default="/dev/fb0")
    ap.add_argument("--tty",          default="/dev/tty7")
    ap.add_argument("--run-dir",      default="/run/nexus-splash")
    ap.add_argument("--disable-file", default=str(_nv / "DISABLED"))
    ap.add_argument("--max-seconds",  type=float, default=90)
    ap.add_argument("--fps",          type=float, default=24)
    ap.add_argument("--wait-fb",      type=float, default=10)
    return ap.parse_args(argv)


if __name__ == "__main__":
    a = parse()
    if os.path.exists(a.disable_file):
        log(f"disabled ({a.disable_file} exists) — not drawing")
        sys.exit(0)
    if not wait_for_device(a.fb, a.wait_fb):
        log(f"{a.fb} did not appear within {a.wait_fb:g}s — not drawing")
        sys.exit(0)
    busy = other_holders(a.fb)
    if busy:
        log(f"{a.fb} already in use by pid(s) {busy} — not drawing")
        sys.exit(0)
    cfg   = read_config(a.config)
    scale = cfg.get("scale", DEFAULT_SCALE)
    if scale not in ("fit", "fill", "stretch"):
        scale = DEFAULT_SCALE
    intro, loop, still, pack_id = resolve_pack(a.build_dir, cfg)
    if not intro:
        log("no built pack found — not drawing")
        sys.exit(0)
    log(f"playing pack: {pack_id}  scale: {scale}")
    sys.exit(Player(a, scale).main(intro, loop, still))
