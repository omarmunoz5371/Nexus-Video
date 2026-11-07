#!/usr/bin/env bash
# nexus-video preflight — hardware and dependency compatibility check.
#
# Verifies that the system meets the minimum requirements for Nexus Video
# before installation begins. Run without root to check the user environment;
# some checks (framebuffer, service state) need sudo context.
#
# Exit codes:
#   0 — all required checks pass (optional items may be missing)
#   1 — one or more required checks failed
#
# Usage:
#   ./deploy/preflight.sh
#   ./deploy/preflight.sh --json          # machine-readable JSON output

set -euo pipefail

# ── options ───────────────────────────────────────────────────────────────────
JSON_OUT=false
for arg in "$@"; do
  case $arg in
    --json) JSON_OUT=true ;;
    -h|--help)
      echo "Usage: $0 [--json]"
      echo "  --json  Output results as JSON instead of human-readable text"
      exit 0 ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

# ── result tracking ───────────────────────────────────────────────────────────
PASS=0
WARN=0
FAIL=0
declare -a RESULTS=()

result() {
  local status="$1" label="$2" detail="$3" required="${4:-true}"
  RESULTS+=("${status}|${required}|${label}|${detail}")
  case "${status}" in
    PASS) PASS=$((PASS+1)) ;;
    WARN) WARN=$((WARN+1)) ;;
    FAIL) [[ "${required}" == "true" ]] && FAIL=$((FAIL+1)) || WARN=$((WARN+1)) ;;
  esac
}

# ── 1. Operating system ───────────────────────────────────────────────────────
OS_ID="$(. /etc/os-release 2>/dev/null && echo "${ID:-unknown}" || echo unknown)"
OS_VER="$(. /etc/os-release 2>/dev/null && echo "${VERSION_ID:-?}" || echo ?)"
OS_PRETTY="$(. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-unknown}" || echo unknown)"

case "${OS_ID}" in
  debian|raspbian)
    if [[ "${OS_VER}" == "12" ]]; then
      result PASS "OS" "Debian/Bookworm (${OS_PRETTY}) — fully supported"
    elif [[ "${OS_VER}" == "11" ]]; then
      result WARN "OS" "Debian/Bullseye (${OS_PRETTY}) — may work but Bookworm preferred"
    else
      result WARN "OS" "${OS_PRETTY} — untested; Bookworm is the reference OS"
    fi ;;
  ubuntu)
    result WARN "OS" "Ubuntu (${OS_PRETTY}) — not a primary target; may work";;
  *)
    result FAIL "OS" "${OS_PRETTY} — unsupported; Raspberry Pi OS Bookworm required" ;;
esac

# ── 2. Architecture ───────────────────────────────────────────────────────────
ARCH="$(uname -m)"
case "${ARCH}" in
  aarch64|arm64)
    result PASS "Architecture" "${ARCH} — Raspberry Pi / CB1 native target" ;;
  armv7l|armv6l)
    result FAIL "Architecture" "${ARCH} — 32-bit ARM is not supported; use a 64-bit OS image" ;;
  x86_64)
    result WARN "Architecture" "${ARCH} — framebuffer splash will not function; Qt UI may work for development" false ;;
  *)
    result WARN "Architecture" "${ARCH} — unknown architecture; may not work" false ;;
esac

# ── 3. RAM ────────────────────────────────────────────────────────────────────
# Minimum: 1 GB (nexus-screen + ffmpeg + player peak ~350 MB)
# Recommended: 2 GB (Raspberry Pi 4B 2 GB or 4 GB)
MEM_KB="$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
MEM_MB=$((MEM_KB / 1024))
if [[ "${MEM_MB}" -ge 1900 ]]; then
  result PASS "RAM" "${MEM_MB} MB available (≥ 2 GB recommended)"
elif [[ "${MEM_MB}" -ge 900 ]]; then
  result WARN "RAM" "${MEM_MB} MB available — minimum met; 2 GB recommended for headroom"
else
  result FAIL "RAM" "${MEM_MB} MB available — minimum is 1 GB"
fi

# ── 4. Available storage ──────────────────────────────────────────────────────
# Minimum: 500 MB free in home directory (3 built packs ≈ 180 MB + nexus_video + build artefacts)
HOME_FREE_KB="$(df --output=avail "${HOME}" 2>/dev/null | tail -1 | tr -d ' ')"
HOME_FREE_MB=$((${HOME_FREE_KB:-0} / 1024))
if [[ "${HOME_FREE_MB}" -ge 1000 ]]; then
  result PASS "Disk (home)" "${HOME_FREE_MB} MB free in ${HOME}"
elif [[ "${HOME_FREE_MB}" -ge 400 ]]; then
  result WARN "Disk (home)" "${HOME_FREE_MB} MB free — minimum met; 1 GB recommended"
else
  result FAIL "Disk (home)" "${HOME_FREE_MB} MB free in ${HOME} — need at least 500 MB"
fi

# ── 5. Display / framebuffer presence ────────────────────────────────────────
if [[ -e /dev/fb0 ]]; then
  FB_INFO="$(cat /sys/class/graphics/fb0/virtual_size 2>/dev/null || echo '?,?')"
  FB_BITS="$(cat /sys/class/graphics/fb0/bits_per_pixel 2>/dev/null || echo '?')"
  result PASS "Framebuffer" "/dev/fb0 found — ${FB_INFO} at ${FB_BITS}bpp"
else
  result FAIL "Framebuffer" "/dev/fb0 not found — physical display required for splash (minimum 480×320)"
fi

# Check display resolution — minimum is 480×320
if [[ -e /sys/class/graphics/fb0/virtual_size ]]; then
  FB_W="$(cut -d, -f1 /sys/class/graphics/fb0/virtual_size)"
  FB_H="$(cut -d, -f2 /sys/class/graphics/fb0/virtual_size)"
  if [[ "${FB_W}" -ge 480 && "${FB_H}" -ge 320 ]]; then
    result PASS "Display resolution" "${FB_W}×${FB_H} — meets 480×320 minimum"
  else
    result FAIL "Display resolution" \
      "${FB_W}×${FB_H} — below minimum 480×320. Nexus Video requires at least 480×320 pixels."
  fi
fi

# Detect pixel format from sysfs channel descriptors
# Supported: RGB565 (16bpp), BGRA8888/RGBA8888/ARGB8888/ABGR8888 (32bpp)
if [[ -e /sys/class/graphics/fb0/bits_per_pixel ]]; then
  FB_BPP="$(cat /sys/class/graphics/fb0/bits_per_pixel 2>/dev/null || echo 0)"
  _r_off="$(cut -d, -f1 /sys/class/graphics/fb0/red   2>/dev/null || echo -1)"
  _r_len="$(cut -d, -f2 /sys/class/graphics/fb0/red   2>/dev/null || echo 0)"
  _g_off="$(cut -d, -f1 /sys/class/graphics/fb0/green 2>/dev/null || echo -1)"
  _g_len="$(cut -d, -f2 /sys/class/graphics/fb0/green 2>/dev/null || echo 0)"
  _b_off="$(cut -d, -f1 /sys/class/graphics/fb0/blue  2>/dev/null || echo -1)"
  _b_len="$(cut -d, -f2 /sys/class/graphics/fb0/blue  2>/dev/null || echo 0)"

  FB_FMT="unsupported"
  if [[ "${FB_BPP}" == "16" && "${_r_off}" == "11" && "${_r_len}" == "5" \
                              && "${_g_off}" == "5"  && "${_g_len}" == "6" \
                              && "${_b_off}" == "0"  && "${_b_len}" == "5" ]]; then
    FB_FMT="RGB565 (rgb565le)"
  elif [[ "${FB_BPP}" == "32" && "${_r_len}" == "8" && "${_g_len}" == "8" && "${_b_len}" == "8" ]]; then
    if   [[ "${_r_off}" == "8"  && "${_g_off}" == "16" && "${_b_off}" == "24" ]]; then FB_FMT="BGRA8888"
    elif [[ "${_r_off}" == "0"  && "${_g_off}" == "8"  && "${_b_off}" == "16" ]]; then FB_FMT="RGBA8888"
    elif [[ "${_r_off}" == "16" && "${_g_off}" == "8"  && "${_b_off}" == "0"  ]]; then FB_FMT="ARGB8888"
    elif [[ "${_r_off}" == "24" && "${_g_off}" == "16" && "${_b_off}" == "8"  ]]; then FB_FMT="ABGR8888"
    fi
  fi

  if [[ "${FB_FMT}" == "unsupported" ]]; then
    result FAIL "Pixel format" \
      "${FB_BPP}bpp (r@${_r_off}/${_r_len} g@${_g_off}/${_g_len} b@${_b_off}/${_b_len}) — not supported. \
Supported: RGB565 (16bpp), BGRA/RGBA/ARGB/ABGR (32bpp)"
  else
    result PASS "Pixel format" "${FB_FMT} — supported by nexus-video player"
  fi
fi

# ── 6. Python version ─────────────────────────────────────────────────────────
# python3.9+ required (3.11 on Bookworm)
PY_VER="$(python3 --version 2>&1 | awk '{print $2}')"
PY_MAJOR="$(echo "${PY_VER}" | cut -d. -f1)"
PY_MINOR="$(echo "${PY_VER}" | cut -d. -f2)"
if [[ "${PY_MAJOR}" -ge 3 && "${PY_MINOR}" -ge 11 ]]; then
  result PASS "Python" "python3 ${PY_VER} — matches Bookworm system Python"
elif [[ "${PY_MAJOR}" -ge 3 && "${PY_MINOR}" -ge 9 ]]; then
  result PASS "Python" "python3 ${PY_VER} — meets minimum (3.9+)"
elif [[ "${PY_MAJOR}" -ge 3 ]]; then
  result FAIL "Python" "python3 ${PY_VER} — minimum is Python 3.9"
else
  result FAIL "Python" "python3 not found or too old"
fi

# ── 7. PyQt6 ─────────────────────────────────────────────────────────────────
if python3 -c "import PyQt6; from PyQt6.QtWidgets import QApplication" 2>/dev/null; then
  QT_VER="$(python3 -c "import PyQt6; print(PyQt6.QtCore.PYQT_VERSION_STR)" 2>/dev/null || echo unknown)"
  result PASS "PyQt6" "PyQt6 ${QT_VER} installed"
else
  result FAIL "PyQt6" "PyQt6 not found — install with: sudo apt install python3-pyqt6"
fi

# ── 8. FFmpeg ─────────────────────────────────────────────────────────────────
if command -v ffmpeg &>/dev/null; then
  FFMPEG_VER="$(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')"
  # Check rawvideo encoder (needed for splash player) and rgb565 pix format
  if ffmpeg -pix_fmts 2>/dev/null | grep -q "rgb565le"; then
    result PASS "FFmpeg" "ffmpeg ${FFMPEG_VER} with rgb565le support"
  else
    result WARN "FFmpeg" "ffmpeg ${FFMPEG_VER} — rgb565le pix_fmt not listed; splash may fail"
  fi
else
  result FAIL "FFmpeg" "ffmpeg not found — install with: sudo apt install ffmpeg"
fi

# ── 9. Klipper ───────────────────────────────────────────────────────────────
if systemctl is-active --quiet klipper 2>/dev/null; then
  result PASS "Klipper" "klipper.service is active"
elif systemctl list-unit-files klipper.service &>/dev/null 2>&1; then
  result WARN "Klipper" "klipper.service installed but not active" false
else
  result WARN "Klipper" "klipper.service not found — Nexus Video works standalone but Klipper integration requires it" false
fi

# ── 10. Moonraker ─────────────────────────────────────────────────────────────
if systemctl is-active --quiet moonraker 2>/dev/null; then
  result PASS "Moonraker" "moonraker.service is active"
elif systemctl list-unit-files moonraker.service &>/dev/null 2>&1; then
  result WARN "Moonraker" "moonraker.service installed but not active" false
else
  result WARN "Moonraker" "moonraker.service not found — update_manager integration requires Moonraker" false
fi

# ── 11. nexus-screen ──────────────────────────────────────────────────────────
if systemctl list-unit-files nexus-screen.service &>/dev/null 2>&1; then
  NS_STATE="$(systemctl is-active nexus-screen 2>/dev/null || echo inactive)"
  result PASS "Nexus Screen" "nexus-screen.service installed (state: ${NS_STATE})"
else
  result FAIL "Nexus Screen" "nexus-screen.service not found — Nexus Screen must be installed first"
fi

# ── 12. nexus-splash.service (conflict) ───────────────────────────────────────
if systemctl is-active --quiet nexus-splash 2>/dev/null; then
  result WARN "nexus-splash" "nexus-splash.service is currently active — migrate.sh will disable it"
else
  result PASS "nexus-splash" "nexus-splash.service not active (or not installed)"
fi

# ── 13. /dev/fb0 write permission ────────────────────────────────────────────
if [[ -e /dev/fb0 ]]; then
  if [[ -w /dev/fb0 ]] || groups | grep -qw video; then
    result PASS "Framebuffer access" "current user has video group membership or fb0 write access"
  else
    result FAIL "Framebuffer access" "user '$(whoami)' is not in the video group — add with: sudo usermod -aG video $(whoami)"
  fi
fi

# ── 14. tty group (for KDSETMODE) ────────────────────────────────────────────
if groups | grep -qw tty; then
  result PASS "TTY access" "current user is in the tty group"
else
  result WARN "TTY access" "user not in tty group — service uses AmbientCapabilities=CAP_SYS_TTY_CONFIG instead" false
fi

# ── output ────────────────────────────────────────────────────────────────────
if $JSON_OUT; then
  echo "{"
  echo "  \"pass\": ${PASS}, \"warn\": ${WARN}, \"fail\": ${FAIL},"
  echo "  \"results\": ["
  total="${#RESULTS[@]}"
  i=0
  for entry in "${RESULTS[@]}"; do
    IFS='|' read -r status required label detail <<< "${entry}"
    comma=","
    [[ $((i+1)) -eq "${total}" ]] && comma=""
    printf '    {"status":"%s","required":%s,"label":"%s","detail":"%s"}%s\n' \
      "${status}" "${required}" "${label}" "${detail//\"/\\\"}" "${comma}"
    i=$((i+1))
  done
  echo "  ]"
  echo "}"
else
  # ── human-readable output ─────────────────────────────────────────────────
  echo ""
  echo "┌─────────────────────────────────────────────────────────────────────┐"
  echo "│  NEXUS VIDEO — System Preflight Check                              │"
  echo "└─────────────────────────────────────────────────────────────────────┘"
  echo ""

  for entry in "${RESULTS[@]}"; do
    IFS='|' read -r status required label detail <<< "${entry}"
    case "${status}" in
      PASS) icon="  ✓" ;;
      WARN) icon="  !" ;;
      FAIL) [[ "${required}" == "true" ]] && icon="  ✗" || icon="  ?" ;;
    esac
    printf "%s  %-24s  %s\n" "${icon}" "${label}" "${detail}"
  done

  echo ""
  echo "──────────────────────────────────────────────────────────────────────"
  printf "  PASS: %d   WARN: %d   FAIL: %d\n" "${PASS}" "${WARN}" "${FAIL}"
  echo "──────────────────────────────────────────────────────────────────────"

  if [[ "${FAIL}" -gt 0 ]]; then
    echo ""
    echo "  INSTALLATION BLOCKED — Minimum system requirements not met."
    echo "  Resolve all ✗ failures above before running install.sh."
    echo ""
    exit 1
  elif [[ "${WARN}" -gt 0 ]]; then
    echo ""
    echo "  System meets minimum requirements. Review ! warnings before proceeding."
    echo ""
  else
    echo ""
    echo "  All checks passed. System is ready for Nexus Video installation."
    echo ""
  fi
fi

exit $([[ "${FAIL}" -gt 0 ]] && echo 1 || echo 0)
