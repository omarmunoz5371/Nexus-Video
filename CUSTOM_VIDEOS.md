# Creating Custom Video Packs for Nexus Video

This guide explains how to create, import, validate, and use your own startup
video pack with Nexus Video.

---

## What is a Pack?

A **pack** is a folder inside `packs/custom/` that contains:

| File | Required | Description |
|------|----------|-------------|
| `pack.json` | Yes | Pack metadata (id, name, description, scale mode) |
| `intro.mp4` | Yes | Plays once at boot, before the main menu appears |
| `loop.mp4` | Yes | Loops on screen while the printer finishes connecting |

Built-in packs (in `packs/builtin/`) follow the same format. Your custom packs
live in `packs/custom/` and are never modified by updates.

---

## Recommended Video Specifications

| Property | Intro | Loop |
|----------|-------|------|
| Duration | **10 seconds** | **5 seconds** |
| Resolution | Any (converted automatically) |
| Aspect ratio | Any (you choose Fit, Fill, or Stretch at import time) |
| Frame rate | 24 fps recommended |
| Codec | H.264 (MP4 container) |
| Audio | Optional — stripped automatically during conversion |

The player outputs video at your display's native resolution (auto-detected
from `/sys/class/graphics/fb0`). Source videos at any resolution are accepted.
**Minimum supported display resolution is 480×320.** The installer will reject
displays below this size before making any changes to your system.

**Seamless loop requirement:** The first frame of `loop.mp4` should visually
match the last frame so the transition back to the loop start is not jarring.
A still frame, a slow-moving ambient scene, or a looping animation all work well.

---

## Creating Your Pack

### Step 1 — Create a pack folder

```
packs/custom/
└── my_pack/
    ├── pack.json
    ├── intro.mp4
    └── loop.mp4
```

Pick a short, lowercase folder name without spaces. This becomes the pack ID.

### Step 2 — Write pack.json

```json
{
  "id":               "my_pack",
  "name":             "My Pack",
  "type":             "custom",
  "version":          "1.0.0",
  "description":      "A short description of your pack.",
  "intro_duration":   10,
  "loop_duration":    5,
  "scale_mode":       "fit",
  "trademark_notice": null,
  "author":           "Your Name",
  "distribution":     "personal"
}
```

**Required fields:** `id`, `name`, `type`, `version`

**scale_mode options:**

| Mode | Behavior | Best for |
|------|----------|----------|
| `fit` | Shows the whole frame; adds black bars if needed | Logos, text, centered content |
| `fill` | Fills the screen completely; crops the edges | Full-bleed cinematic shots |
| `stretch` | Stretches to fill, ignoring aspect ratio | Pre-rendered 800×480 content only |

### Step 3 — Add your videos

Place `intro.mp4` and `loop.mp4` in the same folder as `pack.json`.
Any resolution and frame rate are accepted as source files.

---

## Importing and Validating

### Discover all packs

```bash
python3 nexus_video_cli.py discover
```

Lists every builtin and custom pack found on disk.

### Validate your pack

```bash
python3 nexus_video_cli.py validate --pack my_pack
```

Validation checks:
- `pack.json` is valid JSON with required fields
- `intro.mp4` and `loop.mp4` exist and are readable video files
- Both files contain at least one video stream
- Duration is not zero
- A warning is shown if duration differs by more than 2 seconds from the recommendation

**Common validation errors:**

| Error | Cause | Fix |
|-------|-------|-----|
| `Missing intro.mp4` | File not in pack folder | Add the file |
| `probe failed: No video stream` | File is corrupt or not a video | Re-export your video |
| `duration 0.00s is below minimum` | Empty or corrupt file | Use a valid video file |
| `unsupported extension` | File is not `.mp4`, `.mkv`, `.mov`, etc. | Convert to MP4 |

---

## Converting Your Pack

Converting re-encodes your source videos to your display's native resolution
using the scale mode you chose:

```bash
python3 nexus_video_cli.py convert --pack my_pack --scale-mode fit
```

Output is written to `build/my_pack/`:

```
build/my_pack/
├── intro.mp4       — encoded at display resolution
├── loop.mp4        — encoded at display resolution
├── still.rgb565    — framebuffer hold-still image (auto-generated)
└── build_meta.json — conversion parameters
```

To convert with a different scale mode without re-running validation:

```bash
python3 nexus_video_cli.py convert --pack my_pack --scale-mode fill
```

---

## Seamless Loop Tips

A seamless loop means `loop.mp4` does not visibly jump when it restarts:

- **Static hold:** A single still frame repeated for 5 seconds is the simplest
  seamless loop — the first and last frames are identical.
- **Ambient motion:** Slowly moving content (particles, gradients, flowing lines)
  loops smoothly if the motion vector at the last frame matches the first.
- **Hard cut:** A fast fade to black at the end that returns to the same black
  at the start is effectively seamless at typical playback speeds.

---

## Naming and File Rules

- Pack folder name: lowercase letters, digits, and underscores only. No spaces.
- The `id` field in `pack.json` must match the folder name exactly.
- Do not place source originals and built output in the same directory.
  Source videos live in `packs/custom/<pack_id>/`; built output is in `build/<pack_id>/`.
- Packs in `packs/builtin/` are managed by Nexus Video updates — do not place
  custom content there.

---

## Selecting a Custom Pack from Settings

After converting your pack, it appears automatically in **Settings → Startup Video**:

1. Open Nexus Screen and tap **Settings**.
2. Tap **Startup Video**.
3. Your custom pack is listed alongside the built-in packs.
4. Tap it to select it — the selection is saved immediately.
5. Tap **Preview** to watch the intro and loop play inside Nexus Screen before committing.

Your custom pack files are stored in `packs/custom/<pack_id>/` and the converted
build output in `build/<pack_id>/`. Neither location is affected by Nexus Screen
or Nexus Video updates.

### Validation errors shown in Settings

If a custom pack has a problem, Nexus Screen shows the error without crashing:

| Error displayed | Cause | Fix |
|-----------------|-------|-----|
| `NOT BUILT` badge on tile | Build output is missing or incomplete | Run `convert --pack <id>` |
| Pack does not appear | `pack.json` is missing or not valid JSON | Check the file with `validate --pack <id>` |
| Pack does not appear | Folder is not in `packs/custom/` | Move the folder to the correct location |
| `No preview` in tile | `still.rgb565` missing or wrong size | Re-run `convert --pack <id>` |
| Preview shows black screen | `intro.mp4` or `loop.mp4` could not be decoded | Re-export from your original source |
| Preview shows error overlay | ffmpeg binary not found | Install ffmpeg: `sudo apt install ffmpeg` |

---

## Handover Protocol (Technical)

Nexus Video preserves the splash handover protocol used by Nexus Screen and
Nexus Sounds. The player writes `/run/nexus-splash/player.pid` on startup and
`/run/nexus-splash/released` when it exits. These files are what `klipper_audio.py`
watches to time the startup chime. No configuration changes are needed in
either Nexus Screen or Nexus Sounds when switching packs.
