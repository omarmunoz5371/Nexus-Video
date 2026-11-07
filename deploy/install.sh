#!/usr/bin/env bash
# nexus-video install.sh
#
# Sets up ~/nexus-video/ and applies the Nexus Screen integration patch.
# Must be run as root.
#
# Sequence:
#   1. Create ~/nexus-video/ directory tree
#   2. Copy player.py, config.json, nexus_video module
#   3. Copy build output from nexus-video-dev (or --build-src override)
#   4. Apply nexus-screen-startup-video.patch to ~/nexus-screen
#   5. Report what is ready; leave service enabling to migrate.sh
#
# Usage:
#   sudo ./install.sh [--confirm] [--dry-run] [--build-src /path/to/build]
#
# --dry-run  : print every action without executing it
# --confirm  : required for real writes (safety gate)
# --build-src: directory containing the pack build output (default: ~/nexus-video-dev/build)

set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEV_ROOT="$(cd "${DEPLOY_DIR}/.." && pwd)"           # ~/nexus-video-dev

# ── Detect target user ────────────────────────────────────────────────────────
# When run via sudo the real caller is in SUDO_USER; fall back to logname or
# the user who owns the dev root (covers CB1/mks and any other username).
if [[ -n "${SUDO_USER:-}" ]]; then
  TARGET_USER="${SUDO_USER}"
elif id "$(logname 2>/dev/null)" &>/dev/null 2>&1; then
  TARGET_USER="$(logname)"
else
  # Last resort: owner of the dev root directory
  TARGET_USER="$(stat -c '%U' "${DEV_ROOT}")"
fi
TARGET_HOME="$(getent passwd "${TARGET_USER}" | cut -d: -f6)"
[[ -n "${TARGET_HOME}" ]] || die "Cannot determine home directory for user ${TARGET_USER}"

INSTALL_DIR="${TARGET_HOME}/nexus-video"
NEXUS_SCREEN_DIR="${TARGET_HOME}/nexus-screen"
PATCH_FILE="${DEPLOY_DIR}/nexus-screen-startup-video.patch"
BUILD_SRC="${DEV_ROOT}/build"
DRY_RUN=false
CONFIRM=false

for arg in "$@"; do
  case $arg in
    --dry-run)   DRY_RUN=true ;;
    --confirm)   CONFIRM=true ;;
    --build-src=*) BUILD_SRC="${arg#--build-src=}" ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

log()  { echo "[install] $*"; }
warn() { echo "[install] WARNING: $*" >&2; }
die()  { echo "[install] FATAL: $*" >&2; exit 1; }

run() {
  if $DRY_RUN; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

# ── safety gate ───────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || die "Must run as root (sudo $0)"

if ! $CONFIRM && ! $DRY_RUN; then
  die "Pass --confirm to perform a real install, or --dry-run to preview actions."
fi

log "Starting Nexus Video install..."
$DRY_RUN && log "(DRY RUN — no changes will be made)"

# ── hardware compatibility check ──────────────────────────────────────────────
# Run the preflight script as the target user so it checks the right home dir.
# Skip in dry-run (no hardware access), but always run on a real install.
if ! $DRY_RUN; then
  PREFLIGHT="${DEPLOY_DIR}/preflight.sh"
  if [[ -x "${PREFLIGHT}" ]]; then
    log "Running hardware preflight check..."
    if ! su -s /bin/bash "${TARGET_USER}" -- "${PREFLIGHT}"; then
      echo ""
      echo "  INSTALLATION BLOCKED — Minimum system requirements not met."
      echo "  Resolve the failed checks above, then re-run install.sh."
      echo ""
      exit 1
    fi
    log "Preflight passed."
  else
    warn "preflight.sh not found or not executable — skipping hardware check"
  fi
fi

# ── preflight ─────────────────────────────────────────────────────────────────
log "Preflight checks..."

[[ -f "${DEV_ROOT}/player.py" ]] || \
  die "player.py not found at ${DEV_ROOT}/player.py"

[[ -f "${DEV_ROOT}/config.json" ]] || \
  die "config.json not found at ${DEV_ROOT}/config.json"

[[ -d "${DEV_ROOT}/nexus_video" ]] || \
  die "nexus_video module not found at ${DEV_ROOT}/nexus_video/"

[[ -d "${BUILD_SRC}/nexus_signature" ]] || \
  die "nexus_signature build output not found at ${BUILD_SRC}/nexus_signature/ — build it first"

[[ -f "${BUILD_SRC}/nexus_signature/still.rgb565" ]] || \
  die "nexus_signature/still.rgb565 missing — build is incomplete"

[[ -f "${BUILD_SRC}/nexus_signature/intro.mp4" ]] || \
  die "nexus_signature/intro.mp4 missing — build is incomplete"

[[ -f "${BUILD_SRC}/nexus_signature/loop.mp4" ]] || \
  die "nexus_signature/loop.mp4 missing — build is incomplete"

[[ -f "${PATCH_FILE}" ]] || \
  die "patch file not found: ${PATCH_FILE}"

[[ -d "${NEXUS_SCREEN_DIR}" ]] || \
  die "Nexus Screen not found at ${NEXUS_SCREEN_DIR}"

# Check if the patch is already applied (idempotent)
PATCH_ALREADY_APPLIED=false
if patch --dry-run -p1 -d "${NEXUS_SCREEN_DIR}" --reverse --silent < "${PATCH_FILE}" 2>/dev/null; then
  PATCH_ALREADY_APPLIED=true
  log "Nexus Screen patch already applied — will skip patching step"
else
  # Verify forward apply would succeed
  patch --dry-run -p1 -d "${NEXUS_SCREEN_DIR}" --silent < "${PATCH_FILE}" 2>/dev/null || \
    die "nexus-screen-startup-video.patch does not apply cleanly to ${NEXUS_SCREEN_DIR} — regenerate the patch against the current HEAD"
fi

log "Preflight OK."

# ── directory structure ───────────────────────────────────────────────────────
log "Creating ${INSTALL_DIR}/ directory tree..."
run install -d -o "${TARGET_USER}" -g "${TARGET_USER}" -m 755 "${INSTALL_DIR}"
run install -d -o "${TARGET_USER}" -g "${TARGET_USER}" -m 755 "${INSTALL_DIR}/build"
run install -d -o "${TARGET_USER}" -g "${TARGET_USER}" -m 755 "${INSTALL_DIR}/packs"
run install -d -o "${TARGET_USER}" -g "${TARGET_USER}" -m 755 "${INSTALL_DIR}/packs/builtin"
run install -d -o "${TARGET_USER}" -g "${TARGET_USER}" -m 755 "${INSTALL_DIR}/packs/custom"

# ── detect update vs fresh install ────────────────────────────────────────────
IS_UPDATE=false
if [[ -d "${INSTALL_DIR}" && -f "${INSTALL_DIR}/player.py" ]]; then
  IS_UPDATE=true
  log "Existing installation detected — preserving user preferences and custom packs"
fi

# ── core files ────────────────────────────────────────────────────────────────
log "Copying player.py..."
run install -o "${TARGET_USER}" -g "${TARGET_USER}" -m 644 "${DEV_ROOT}/player.py" "${INSTALL_DIR}/player.py"

# config.json: only written on fresh install; existing installs keep user preferences
if $IS_UPDATE && [[ -f "${INSTALL_DIR}/config.json" ]]; then
  log "Skipping config.json — existing user preferences preserved (${INSTALL_DIR}/config.json)"
else
  log "Installing default config.json..."
  run install -o "${TARGET_USER}" -g "${TARGET_USER}" -m 644 "${DEV_ROOT}/config.json" "${INSTALL_DIR}/config.json"
fi

log "Copying nexus_video module..."
if ! $DRY_RUN; then
  rsync -a --delete --chown="${TARGET_USER}:${TARGET_USER}" "${DEV_ROOT}/nexus_video/" "${INSTALL_DIR}/nexus_video/"
else
  echo "[dry-run] rsync -a --delete --chown=${TARGET_USER}:${TARGET_USER} ${DEV_ROOT}/nexus_video/ ${INSTALL_DIR}/nexus_video/"
fi

log "Copying builtin pack manifests (pack.json only — not source videos)..."
for pack_dir in "${DEV_ROOT}/packs/builtin"/*/; do
  pack_name="$(basename "${pack_dir}")"
  if [[ -f "${pack_dir}/pack.json" ]]; then
    run install -d -o "${TARGET_USER}" -g "${TARGET_USER}" -m 755 "${INSTALL_DIR}/packs/builtin/${pack_name}"
    run install -o "${TARGET_USER}" -g "${TARGET_USER}" -m 644 "${pack_dir}/pack.json" \
        "${INSTALL_DIR}/packs/builtin/${pack_name}/pack.json"
    log "  → packs/builtin/${pack_name}/pack.json"
  fi
done

# custom/ pack directory: never modified on update — user's custom videos are preserved
if $IS_UPDATE && [[ -d "${INSTALL_DIR}/packs/custom" ]]; then
  log "Custom packs directory preserved — not modified (${INSTALL_DIR}/packs/custom/)"
else
  run install -d -o "${TARGET_USER}" -g "${TARGET_USER}" -m 755 "${INSTALL_DIR}/packs/custom"
  log "Created ${INSTALL_DIR}/packs/custom/ (place your custom video packs here)"
fi

log "Copying CUSTOM_VIDEOS.md..."
run install -o "${TARGET_USER}" -g "${TARGET_USER}" -m 644 "${DEV_ROOT}/CUSTOM_VIDEOS.md" "${INSTALL_DIR}/CUSTOM_VIDEOS.md"

# ── build output ──────────────────────────────────────────────────────────────
log "Copying pack build output from ${BUILD_SRC}/..."
# Copy all pack build directories that have the three required files
for pack_dir in "${BUILD_SRC}"/*/; do
  pack_name="$(basename "${pack_dir}")"
  if [[ -f "${pack_dir}/intro.mp4" && -f "${pack_dir}/loop.mp4" && -f "${pack_dir}/still.rgb565" ]]; then
    log "  → pack: ${pack_name}"
    run install -d -o "${TARGET_USER}" -g "${TARGET_USER}" -m 755 "${INSTALL_DIR}/build/${pack_name}"
    if ! $DRY_RUN; then
      rsync -a --chown="${TARGET_USER}:${TARGET_USER}" "${pack_dir}" "${INSTALL_DIR}/build/${pack_name}/"
    else
      echo "[dry-run] rsync -a --chown=${TARGET_USER}:${TARGET_USER} ${pack_dir} ${INSTALL_DIR}/build/${pack_name}/"
    fi
  else
    warn "Skipping incomplete pack: ${pack_name}"
  fi
done

# ── verify ConditionPathExists target ────────────────────────────────────────
if ! $DRY_RUN; then
  [[ -f "${INSTALL_DIR}/build/nexus_signature/still.rgb565" ]] || \
    die "Post-install check failed: nexus_signature/still.rgb565 missing — service would silently skip"
  log "Service startup condition satisfied: nexus_signature/still.rgb565 present"
fi

# ── apply nexus-screen patch ──────────────────────────────────────────────────
if $PATCH_ALREADY_APPLIED; then
  log "Nexus Screen patch: already applied — skipping"
else
  log "Applying nexus-screen-startup-video.patch to ${NEXUS_SCREEN_DIR}..."
  if ! $DRY_RUN; then
    patch -p1 -d "${NEXUS_SCREEN_DIR}" < "${PATCH_FILE}"
    log "Patch applied successfully."
  else
    echo "[dry-run] patch -p1 -d ${NEXUS_SCREEN_DIR} < ${PATCH_FILE}"
  fi
fi

# ── install service unit ──────────────────────────────────────────────────────
log "Installing nexus-video.service (user=${TARGET_USER}, home=${TARGET_HOME})..."
if ! $DRY_RUN; then
  # Substitute @@USER@@ with the actual target user before installing
  sed "s|@@USER@@|${TARGET_USER}|g" \
    "${DEPLOY_DIR}/nexus-video.service" \
    > /tmp/nexus-video.service.tmp
  install -o root -g root -m 644 \
    /tmp/nexus-video.service.tmp \
    /etc/systemd/system/nexus-video.service
  rm -f /tmp/nexus-video.service.tmp
else
  echo "[dry-run] sed 's|@@USER@@|${TARGET_USER}|g' ${DEPLOY_DIR}/nexus-video.service > /etc/systemd/system/nexus-video.service"
fi
run systemctl daemon-reload
log "nexus-video.service unit installed (not yet enabled — run migrate.sh to switch services)"

# ── summary ───────────────────────────────────────────────────────────────────
if $DRY_RUN; then
  log "DRY RUN complete — no changes made."
else
  log ""
  log "Install complete!"
  log "  → ${INSTALL_DIR}/player.py"
  log "  → ${INSTALL_DIR}/config.json"
  log "  → ${INSTALL_DIR}/nexus_video/"
  log "  → ${INSTALL_DIR}/build/nexus_signature/ (service startup condition satisfied)"
  log "  → Nexus Screen patch: applied"
  log "  → /etc/systemd/system/nexus-video.service: installed"
  log ""
  log "Next step: sudo ${DEPLOY_DIR}/migrate.sh"
  log "  This disables nexus-splash.service, enables nexus-video.service,"
  log "  and takes effect on next boot."
fi
