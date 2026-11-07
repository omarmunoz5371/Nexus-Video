# Nexus Video

> Cinematic boot splash add-on for [Nexus Screen](https://github.com/omarmunoz5371/Nexus-Screen).

Nexus Video replaces the default Nexus Screen static splash with animated startup
video packs. It plays a 10-second intro once at boot, then loops ambient video
while the printer connects — with no desktop environment required.

**Status: Public Beta**  
Requires Nexus Screen v0.2.0-beta.4 or later.

---

## Features

- **Three built-in packs** — Nexus Signature, Mechanical Core, System Initialization
- **Custom packs** — drop in your own `intro.mp4` and `loop.mp4`
- **Adaptive display scaling** — auto-detects framebuffer resolution and pixel format
- **Fit / Fill / Stretch** — choose how video fills your display per pack
- **Minimum resolution: 480×320** — all verified touch-accessible at this size; 800×480 is the reference
- **Multi-format framebuffer** — supports RGB565 (16bpp) and BGRA/RGBA/ARGB/ABGR (32bpp)
- **Preserves custom packs and preferences** on update
- **Handover protocol compatible** with Nexus Sounds (startup chime timing unchanged)

---

## Minimum Requirements

| Requirement | Minimum |
|---|---|
| **Nexus Screen** | v0.2.0-beta.4 or later (must be installed first) |
| **SBC** | Raspberry Pi 4 or BigTreeTech CB1, 64-bit (aarch64) |
| **OS** | Debian 12 (Bookworm) or Raspberry Pi OS (Bookworm), 64-bit |
| **RAM** | 1 GB (2 GB recommended) |
| **Free disk** | 500 MB in home directory |
| **Display** | Physical framebuffer at `/dev/fb0`, minimum **480×320** |
| **Pixel format** | RGB565 (16bpp) or BGRA/RGBA/ARGB/ABGR (32bpp) |
| **Python** | 3.9+ (Python 3.11 included with Bookworm) |
| **FFmpeg** | Any recent version — `sudo apt install ffmpeg` |

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/omarmunoz5371/Nexus-Video.git ~/nexus-video

# 2. Run the hardware preflight check (no changes made)
bash ~/nexus-video/deploy/preflight.sh

# 3. Install
bash ~/nexus-video/deploy/install.sh
```

The installer:
1. Runs a hardware preflight check; stops with "INSTALLATION BLOCKED" if requirements are not met — no system changes are made.
2. Installs Nexus Video files to `~/nexus-video/`.
3. Configures and enables `nexus-video.service`.
4. Disables `nexus-splash.service` (Nexus Screen's built-in static splash).

**On update**, your `config.json` (pack selection) and `packs/custom/` (custom packs) are preserved.

---

## Updating

### Via Moonraker Update Manager (recommended)

Add the following to your `moonraker.conf`, then restart Moonraker:

```ini
[update_manager nexus-video]
type: git_repo
path: ~/nexus-video
origin: https://github.com/omarmunoz5371/Nexus-Video.git
primary_branch: main
is_system_service: False
managed_services: nexus-video
```

See [`deploy/moonraker-update-manager.conf`](deploy/moonraker-update-manager.conf) for the full snippet.

### Manual update

```bash
cd ~/nexus-video
git pull
bash deploy/install.sh
```

---

## Uninstalling

```bash
bash ~/nexus-video/deploy/uninstall.sh
```

Uninstalling re-enables `nexus-splash.service` and removes `nexus-video.service`.
Your `packs/custom/` files are not deleted.

---

## Custom Video Packs

See **[CUSTOM_VIDEOS.md](CUSTOM_VIDEOS.md)** for a step-by-step guide on creating,
validating, and importing your own packs.

Quick summary:

```bash
# Validate a custom pack
python3 nexus_video_cli.py validate --pack my_pack

# Convert to your display's resolution
python3 nexus_video_cli.py convert --pack my_pack --scale-mode fit
```

Custom packs live in `packs/custom/` and are never modified by updates.

---

## Integrating with Nexus Screen

Nexus Video adds a **Startup Video** screen to the Nexus Screen Settings section.
Apply the integration patch to your Nexus Screen installation:

```bash
# From your nexus-screen directory
git apply ~/nexus-video/deploy/nexus-screen-startup-video.patch
```

---

## Troubleshooting

```bash
# Check service status
systemctl status nexus-video

# View recent logs
journalctl -u nexus-video -b --no-pager | tail -40

# Re-run hardware preflight
bash ~/nexus-video/deploy/preflight.sh
```

**Common issues:**

| Symptom | Cause | Fix |
|---|---|---|
| Black screen at boot | Pack not built | Run `convert --pack nexus_signature` |
| "INSTALLATION BLOCKED" | Hardware requirement not met | Read preflight output and fix the listed failures |
| Service fails to start | Missing FFmpeg | `sudo apt install ffmpeg` |
| still frame wrong size | Display resolution differs from build | A companion `still.png` is used automatically as fallback |
| No splash at all | Service not enabled | `sudo systemctl enable --now nexus-video` |

---

## License

Nexus Video is released under the [GNU General Public License v3.0](LICENSE).

---

## Related

- **[Nexus Screen](https://github.com/omarmunoz5371/Nexus-Screen)** — the touchscreen UI this add-on extends
