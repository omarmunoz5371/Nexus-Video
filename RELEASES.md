# Nexus Video — Release Notes

---

## v0.1.0-beta.1 — Public Beta (Release Candidate)

> Compatible with Nexus Screen v0.2.0-beta.5.

### What is Nexus Video?

Nexus Video is an optional add-on for [Nexus Screen](https://github.com/TheOmProject/Nexus-Screen).
It replaces the default static boot splash with animated video packs. It plays a 10-second
animated intro once at boot, then loops ambient video while the printer connects — with no
desktop environment required.

Installing Nexus Video is entirely optional. Nexus Screen functions normally without it.

---

### New in this release

**Three built-in video packs:**
- **Nexus Signature** — official theme: white-on-black grid reveal with the Nexus wordmark
- **Mechanical Core** — cinematic macro shots of CoreXY motion components (linear rails, belts, gantry)
- **System Init** — retro green-on-black terminal boot sequence aesthetic

**Hardware:**
- Display auto-detection: reads resolution and pixel format from sysfs at startup
- Minimum supported resolution: **480×320** (installer blocks below this)
- Supported pixel formats: RGB565 (16bpp), BGRA8888/RGBA8888/ARGB8888/ABGR8888 (32bpp)
- Resolution-aware still frame fallback: if `still.rgb565` doesn't match the display size,
  a companion `still.png` is converted at runtime — no crash

**Scale modes:**
- **Fit** — letterbox (black bars); default; best for logos and text
- **Fill** — scale and crop to fill the screen; best for cinematic shots
- **Stretch** — scale without preserving aspect ratio

**Installer:**
- Hardware preflight check with 14 requirements before any file writes
- Supported hardware check includes Raspberry Pi 4, BigTreeTech CB1
- Incompatible hardware: installer prints "INSTALLATION BLOCKED" and exits
- Fresh install and update mode; config and custom packs preserved on update

**Nexus Screen integration:**
- **Settings → Startup Video** screen: browse, preview, and switch packs in-app
- In-app video preview using FFmpeg
- Graceful degradation: when Nexus Video is absent, the tile shows an installation notice

**Moonraker Update Manager:**
- Independent git-based update entry at `deploy/moonraker-update-manager.conf`
- Updates preserve `config.json` (selected pack) and `packs/custom/` (user packs)

**Custom packs:**
- Drop `intro.mp4` + `loop.mp4` + `pack.json` into `packs/custom/<pack_id>/`
- Full guide at [CUSTOM_VIDEOS.md](CUSTOM_VIDEOS.md)

---

### Minimum requirements

| Requirement | Minimum |
|---|---|
| Nexus Screen | v0.2.0-beta.5 or later |
| SBC | Raspberry Pi 4 or BigTreeTech CB1 (64-bit, aarch64) |
| OS | Debian 12 (Bookworm), 64-bit |
| RAM | 1 GB (2 GB recommended) |
| Free disk | 500 MB |
| Display | Physical `/dev/fb0` framebuffer, minimum 480×320 |
| Pixel format | RGB565 (16bpp) or 32bpp BGRA/RGBA/ARGB/ABGR |
| Python | 3.9+ |
| FFmpeg | Any recent version |

---

### Known limitations

- **Framebuffer playback not physically verified** — the complete `public-install.sh` → service → boot sequence has not been run end-to-end on any device; FFmpeg conversion has been verified in isolation on Raspberry Pi 4 (800×480 RGB565)
- Built-in packs are built for 800×480 reference resolution; displayed at any resolution via adaptive FFmpeg scaling
- In-app preview requires FFmpeg to be installed
- No audio (startup chime is handled by Nexus Sounds, which remains unmodified)
- Raspberry Pi 3, Pi 5, Pi Zero 2 W, HDMI and SPI displays: not tested

---

### Installation

**Via Nexus Screen bootstrap (recommended — installs both together):**
```bash
curl -fsSL https://raw.githubusercontent.com/TheOmProject/Nexus-Screen/main/deploy/bootstrap.sh | bash -s -- --with-video
```

**Standalone — add to existing Nexus Screen:**
```bash
git clone https://github.com/TheOmProject/Nexus-Video.git ~/nexus-video
sudo bash ~/nexus-video/deploy/public-install.sh
```

---

### Nexus Screen compatibility

This release is compatible with **Nexus Screen v0.2.0-beta.5**, which includes the
Startup Video integration patch (`nexus/screens/startup_video.py`).

Earlier Nexus Screen versions (before v0.2.0-beta.5) do not include the Startup Video
settings screen. Nexus Video can still be installed as a standalone boot splash — it
operates independently of Nexus Screen for the actual framebuffer playback.
