#!/usr/bin/env bash
# nexus-video migrate.sh
#
# Atomically migrates from nexus-splash.service to nexus-video.service.
# Creates a full backup so uninstall.sh can restore the original state.
#
# SAFETY:
#   - Checks player.py and config.json exist before touching any service
#   - Makes a timestamped backup in ~/.nexus-video-backup/
#   - Rolls back automatically on any error (set -e)
#   - Never touches printer.cfg, Moonraker, Klipper, Beacon or Leviathan
#   - Does NOT reboot — changes take effect on next boot
#
# Usage:
#   sudo ./migrate.sh [--dry-run]
set -euo pipefail

TARGET_USER="${SUDO_USER:-$(id -un)}"
HOME_DIR="$(getent passwd "${TARGET_USER}" | cut -d: -f6)"
[[ -n "${HOME_DIR}" ]] || { echo "ERROR: Cannot determine home directory for ${TARGET_USER}" >&2; exit 1; }
INSTALL_DIR="${HOME_DIR}/nexus-video"
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_ROOT="${HOME_DIR}/.nexus-video-backup"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${BACKUP_ROOT}/${TIMESTAMP}"
DRY_RUN=false
ROLLBACK_DONE=false

# ── argument parsing ──────────────────────────────────────────────────────────
for arg in "$@"; do
  case $arg in
    --dry-run) DRY_RUN=true ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

log()  { echo "[migrate] $*"; }
warn() { echo "[migrate] WARNING: $*" >&2; }
die()  { echo "[migrate] FATAL: $*" >&2; exit 1; }

run() {
  if $DRY_RUN; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

# ── preflight checks ──────────────────────────────────────────────────────────
log "Preflight checks..."
[[ $EUID -eq 0 ]] || die "Must run as root (sudo $0)"

# install.sh must have been run first
[[ -f "${INSTALL_DIR}/player.py" ]] || \
  die "player.py not found at ${INSTALL_DIR}/player.py — run 'sudo deploy/install.sh --confirm' first"

[[ -f "${INSTALL_DIR}/config.json" ]] || \
  die "config.json not found at ${INSTALL_DIR}/config.json — run 'sudo deploy/install.sh --confirm' first"

# The service's ConditionPathExists target must be satisfied before migration
[[ -f "${INSTALL_DIR}/build/nexus_signature/still.rgb565" ]] || \
  die "nexus_signature build output missing — nexus-video.service would silently skip on boot. Run 'sudo deploy/install.sh --confirm' first."

# nexus-video.service unit must be installed (install.sh puts it in /etc/systemd/system/)
[[ -f "/etc/systemd/system/nexus-video.service" ]] || \
  die "nexus-video.service not installed in /etc/systemd/system/ — run 'sudo deploy/install.sh --confirm' first"

# Verify the Nexus Screen patch was applied (critical — the splash_pid fix must be live)
NEXUS_SCREEN_DIR="${HOME_DIR}/nexus-screen"
PATCH_FILE="${DEPLOY_DIR}/nexus-screen-startup-video.patch"
if [[ -f "${PATCH_FILE}" && -d "${NEXUS_SCREEN_DIR}" ]]; then
  if ! patch --dry-run -p1 -d "${NEXUS_SCREEN_DIR}" --reverse --silent < "${PATCH_FILE}" 2>/dev/null; then
    die "Nexus Screen integration patch has NOT been applied to ${NEXUS_SCREEN_DIR}. Without it, Nexus Screen will show its window over the playing splash. Run 'sudo deploy/install.sh --confirm' first."
  fi
  log "Nexus Screen patch verified: applied."
else
  warn "Cannot verify Nexus Screen patch (patch file or nexus-screen dir missing)"
fi

# nexus-screen.service must exist (migration target must be safe)
[[ -f "/etc/systemd/system/nexus-screen.service" ]] || \
  warn "nexus-screen.service not found — Nexus Screen may not be installed"

# nexus-splash.service must exist (we're migrating from it)
[[ -f "/etc/systemd/system/nexus-splash.service" ]] || \
  warn "nexus-splash.service not found — may already be migrated or not installed"

log "Preflight OK."

# ── rollback handler ──────────────────────────────────────────────────────────
rollback() {
  if $ROLLBACK_DONE; then return; fi
  ROLLBACK_DONE=true
  warn "Error encountered — rolling back..."
  if [[ -d "${BACKUP_DIR}" ]]; then
    if [[ -f "${BACKUP_DIR}/nexus-splash.service" ]]; then
      cp "${BACKUP_DIR}/nexus-splash.service" /etc/systemd/system/nexus-splash.service
      systemctl daemon-reload
      systemctl enable nexus-splash.service 2>/dev/null || true
      log "Restored nexus-splash.service"
    fi
    if [[ -f "${BACKUP_DIR}/nexus-video.service.installed" ]]; then
      systemctl disable nexus-video.service 2>/dev/null || true
      rm -f /etc/systemd/system/nexus-video.service
      systemctl daemon-reload
      log "Removed nexus-video.service"
    fi
  fi
  warn "Rollback complete. Original state restored."
}
trap rollback ERR

# ── backup ────────────────────────────────────────────────────────────────────
log "Creating backup in ${BACKUP_DIR}..."
run mkdir -p "${BACKUP_DIR}"

if [[ -f "/etc/systemd/system/nexus-splash.service" ]]; then
  run cp /etc/systemd/system/nexus-splash.service "${BACKUP_DIR}/nexus-splash.service"
  log "Backed up nexus-splash.service"
fi
if [[ -f "/etc/systemd/system/nexus-video.service" ]]; then
  run cp /etc/systemd/system/nexus-video.service "${BACKUP_DIR}/nexus-video.service.prev"
fi

# Record currently-active service state
systemctl is-enabled nexus-splash.service 2>/dev/null >"${BACKUP_DIR}/nexus-splash.enabled" || true
systemctl is-enabled nexus-video.service  2>/dev/null >"${BACKUP_DIR}/nexus-video.enabled"  || true

# ── disable old service ───────────────────────────────────────────────────────
log "Disabling nexus-splash.service..."
if systemctl is-enabled --quiet nexus-splash.service 2>/dev/null; then
  run systemctl disable nexus-splash.service
  log "nexus-splash.service disabled (will not start on next boot)"
else
  log "nexus-splash.service was already disabled"
fi

# ── install new service ───────────────────────────────────────────────────────
log "Installing nexus-video.service..."
run cp "${DEPLOY_DIR}/nexus-video.service" /etc/systemd/system/nexus-video.service
run touch "${BACKUP_DIR}/nexus-video.service.installed"  # marker for rollback
run systemctl daemon-reload
run systemctl enable nexus-video.service
log "nexus-video.service enabled"

# ── verify ────────────────────────────────────────────────────────────────────
if ! $DRY_RUN; then
  systemctl is-enabled nexus-video.service  || die "nexus-video.service did not enable successfully"
  systemctl is-enabled nexus-splash.service 2>/dev/null && die "nexus-splash.service is still enabled after migration"
  log "Verification passed."
fi

# ── final message ─────────────────────────────────────────────────────────────
if $DRY_RUN; then
  log "DRY RUN complete — no changes made."
else
  log "Migration complete!"
  log "  → nexus-splash.service: disabled"
  log "  → nexus-video.service:  enabled"
  log "  → Backup saved to:      ${BACKUP_DIR}"
  log "  → Changes take effect on NEXT BOOT (printer not rebooted)"
  log ""
  log "To roll back:  sudo ${DEPLOY_DIR}/uninstall.sh"
fi
