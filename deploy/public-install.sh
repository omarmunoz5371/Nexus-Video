#!/usr/bin/env bash
# Nexus Video — public installer.
# Designed for the end-user flow: works from a fresh git clone with no
# pre-built artifacts.
#
# Usage:
#   sudo bash ~/nexus-video/deploy/public-install.sh
#   sudo bash ~/nexus-video/deploy/public-install.sh --dry-run
#
# This installer:
#   1. Runs hardware preflight check
#   2. Converts each builtin pack (source MP4 → still.rgb565, encoded output)
#   3. Creates a default config.json (preserves an existing one)
#   4. Installs nexus-video.service to /etc/systemd/system/
#   5. Runs migrate.sh to switch nexus-splash → nexus-video at next boot
#
# Safety:
#   - Never modifies Klipper, Moonraker, or printer.cfg
#   - Preserves an existing config.json (pack selection is not reset)
#   - migrate.sh creates a timestamped backup before touching any service
#   - Changes take effect at next boot, not immediately

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

DRY_RUN=false
for arg in "$@"; do
  case $arg in
    --dry-run) DRY_RUN=true ;;
    -h|--help)
      printf 'Usage: sudo bash %s [--dry-run]\n' "$0"
      exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$arg" >&2; exit 1 ;;
  esac
done

# ── helpers ───────────────────────────────────────────────────────────────────
log()  { printf '[nexus-video] %s\n' "$*"; }
die()  { printf '[nexus-video] FATAL: %s\n' "$*" >&2; exit 1; }
warn() { printf '[nexus-video] WARNING: %s\n' "$*" >&2; }

run() {
  if $DRY_RUN; then
    printf '[dry-run] %s\n' "$*"
  else
    "$@"
  fi
}

# ── identity ──────────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || die "Must run as root: sudo bash $0"

if [[ -n "${SUDO_USER:-}" ]]; then
  TARGET_USER="${SUDO_USER}"
else
  TARGET_USER="$(stat -c '%U' "${REPO_DIR}")"
fi
TARGET_HOME="$(getent passwd "${TARGET_USER}" | cut -d: -f6)"
[[ -n "${TARGET_HOME}" ]] || die "Cannot determine home directory for ${TARGET_USER}"

# Confirm we are in the right repo
[[ -f "${REPO_DIR}/player.py" ]] || die "player.py not found — run from ~/nexus-video"
[[ -d "${REPO_DIR}/nexus_video" ]] || die "nexus_video/ module not found"
[[ -d "${REPO_DIR}/packs/builtin" ]] || die "packs/builtin/ not found"

BUILD_DIR="${REPO_DIR}/build"
CONFIG_FILE="${REPO_DIR}/config.json"
SERVICE_TMPL="${SCRIPT_DIR}/nexus-video.service"
MIGRATE_SH="${SCRIPT_DIR}/migrate.sh"

[[ -f "${SERVICE_TMPL}" ]] || die "Service template not found: ${SERVICE_TMPL}"

log "Installing Nexus Video for user: ${TARGET_USER}"
$DRY_RUN && log "(DRY RUN — no changes will be made)"

# ── step 1: preflight ─────────────────────────────────────────────────────────
log ""
log "Step 1/4: Preflight check"

PREFLIGHT="${SCRIPT_DIR}/preflight.sh"
if [[ -x "${PREFLIGHT}" ]]; then
  if ! $DRY_RUN; then
    if ! su -s /bin/bash "${TARGET_USER}" -- "${PREFLIGHT}"; then
      die "Preflight check failed — resolve the issues above and retry."
    fi
  else
    log "[dry-run] would run: ${PREFLIGHT}"
  fi
else
  warn "preflight.sh not found or not executable — skipping"
fi

# ── step 2: build video packs ──────────────────────────────────────────────────
log ""
log "Step 2/4: Building video packs (this may take a few minutes)"

run mkdir -p "${BUILD_DIR}"
if ! $DRY_RUN; then
  chown "${TARGET_USER}:${TARGET_USER}" "${BUILD_DIR}"
fi

PACKS_OK=()
PACKS_FAIL=()
for pack_dir in "${REPO_DIR}/packs/builtin"/*/; do
  [[ -d "${pack_dir}" ]] || continue
  pack_id="$(basename "${pack_dir}")"
  if [[ ! -f "${pack_dir}/intro.mp4" ]] || [[ ! -f "${pack_dir}/pack.json" ]]; then
    warn "  skip ${pack_id}: incomplete source (no intro.mp4 or pack.json)"
    continue
  fi
  log "  converting: ${pack_id}"
  if $DRY_RUN; then
    log "  [dry-run] python3 ${REPO_DIR}/nexus_video_cli.py convert --pack ${pack_id} --scale-mode fit"
    PACKS_OK+=("${pack_id}")
  else
    if su -s /bin/bash "${TARGET_USER}" -- \
        python3 "${REPO_DIR}/nexus_video_cli.py" convert \
          --pack "${pack_id}" --scale-mode fit 2>&1; then
      PACKS_OK+=("${pack_id}")
      log "  ✓ ${pack_id}"
    else
      PACKS_FAIL+=("${pack_id}")
      warn "  ✗ ${pack_id}: conversion failed"
    fi
  fi
done

if ! $DRY_RUN; then
  [[ -f "${BUILD_DIR}/nexus_signature/still.rgb565" ]] || \
    die "nexus_signature still.rgb565 not found after conversion — check FFmpeg and /dev/fb0"
  log "  Service condition satisfied: nexus_signature/still.rgb565 present"
fi

# ── step 3: config.json ────────────────────────────────────────────────────────
log ""
log "Step 3/4: Configuration"

if [[ -f "${CONFIG_FILE}" ]]; then
  log "  Existing config.json preserved (pack selection unchanged)"
else
  log "  Creating default config.json (nexus_signature, fit mode)"
  if $DRY_RUN; then
    log "  [dry-run] write ${CONFIG_FILE}"
  else
    cat > "${CONFIG_FILE}" <<'CONFJSON'
{
  "selected_pack": "nexus_signature",
  "scale_mode": "fit"
}
CONFJSON
    chown "${TARGET_USER}:${TARGET_USER}" "${CONFIG_FILE}"
  fi
fi

# ── step 4: install + migrate service ─────────────────────────────────────────
log ""
log "Step 4/4: Service installation"

log "  Installing nexus-video.service..."
if $DRY_RUN; then
  log "  [dry-run] install nexus-video.service (user=${TARGET_USER})"
else
  _svc_tmp="$(mktemp /tmp/nexus-video.service.XXXXXX)"
  sed "s|@@USER@@|${TARGET_USER}|g" "${SERVICE_TMPL}" > "${_svc_tmp}"
  install -o root -g root -m 644 "${_svc_tmp}" /etc/systemd/system/nexus-video.service
  rm -f "${_svc_tmp}"
  systemctl daemon-reload
fi

log "  Running migrate.sh (nexus-splash → nexus-video at next boot)..."
if [[ -x "${MIGRATE_SH}" ]]; then
  if $DRY_RUN; then
    log "  [dry-run] sudo ${MIGRATE_SH} --dry-run"
  else
    bash "${MIGRATE_SH}"
  fi
else
  warn "migrate.sh not found — service installed but not activated"
  if ! $DRY_RUN; then
    systemctl enable nexus-video.service
    log "  nexus-video.service enabled directly"
  fi
fi

# ── summary ───────────────────────────────────────────────────────────────────
log ""
if $DRY_RUN; then
  log "DRY RUN complete — no changes made."
else
  log "Nexus Video installed successfully!"
  log "  Packs built: ${PACKS_OK[*]:-none}"
  if [[ ${#PACKS_FAIL[@]} -gt 0 ]]; then
    warn "  Packs failed: ${PACKS_FAIL[*]}"
    warn "  Retry individual packs: python3 nexus_video_cli.py convert --pack <name>"
  fi
  log "  Config:  ${CONFIG_FILE}"
  log "  Service: nexus-video.service (enabled, starts at next boot)"
  log ""
  log "  Changes take effect on NEXT REBOOT."
  log "  To roll back:  sudo ${SCRIPT_DIR}/uninstall.sh"
fi
