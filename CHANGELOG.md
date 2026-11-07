# Changelog

All notable changes to Nexus Video are documented here.
Dates are in YYYY-MM-DD format.

---

## [Unreleased] — Public Beta

Initial public beta of Nexus Video as a standalone add-on for Nexus Screen.

### Added

**Core player (`player.py`)**
- Framebuffer auto-detection: reads resolution and pixel format from sysfs at startup
- Supported pixel formats: RGB565 (16bpp), BGRA8888, RGBA8888, ARGB8888, ABGR8888 (32bpp)
- Minimum display resolution enforced: 480×320 (player exits cleanly below this)
- Fit / Fill / Stretch scale modes via FFmpeg `vf` filter — applied per pack from `config.json`
- Resolution-aware still.rgb565 fallback: if the still size does not match the display, a companion `still.png` is used and converted at runtime with FFmpeg
- Capability drop (`PR_CAP_AMBIENT_CLEAR_ALL`) before each FFmpeg subprocess
- Handover protocol: writes `/run/nexus-splash/player.pid` and `/run/nexus-splash/released` — compatible with Nexus Sounds

**Pack system (`nexus_video/`)**
- Pack discovery: scans `packs/builtin/` and `packs/custom/` for valid `pack.json` manifests
- Pack validation: required fields, video stream check, duration, file existence
- Pack conversion: FFmpeg re-encode to display resolution with Fit / Fill / Stretch
- Custom pack support: `packs/custom/` is never modified by updates

**Built-in packs (`packs/builtin/`)**
- `nexus_signature` — official Nexus Video theme: white-on-black grid reveal with the Nexus wordmark
- `mechanical_core` — cinematic macro shots of Voron motion components
- `system_init` — green-on-black terminal boot sequence aesthetic

**Installer (`deploy/install.sh`)**
- Hardware preflight check runs before any file writes — failed checks block installation with no system changes
- Update detection: config.json and packs/custom/ are preserved on update
- Service parameterization via `@@USER@@` substitution; `%h` systemd specifier for home directory paths

**Preflight check (`deploy/preflight.sh`)**
- 14 checks: OS, architecture, RAM, disk, framebuffer presence, display resolution (≥480×320), pixel format, Python, PyQt6, FFmpeg, Klipper, Moonraker, Nexus Screen, video/tty group membership
- Hard FAILs block installation; optional items are warnings
- `--json` flag for machine-readable output

**Nexus Screen integration**
- `deploy/nexus-screen-startup-video.patch` — applies startup video screen and video preview to Nexus Screen
- `nexus/screens/startup_video.py` — adaptive Phase C layout (sx/sy/smin/cx helpers)
- `nexus/screens/video_preview.py` — inline video preview using FFmpeg
- Graceful degradation: when Nexus Video is not installed, the Settings screen shows a notice rather than crashing

**Moonraker integration**
- `deploy/moonraker-update-manager.conf` — ready-to-paste Moonraker `update_manager` block

**Documentation**
- `README.md` — installation, requirements, update, troubleshooting
- `CUSTOM_VIDEOS.md` — full guide to creating and importing custom packs
- `deploy/nexus-video.service` — documented parameterized systemd unit
- Minimum supported display resolution stated as 480×320 throughout

---

*Previous development history is tracked in the private development repository.*
