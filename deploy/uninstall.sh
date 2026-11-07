#!/usr/bin/env bash
# nexus-video uninstall.sh
#
# Reverses the migration: re-enables nexus-splash.service and removes
# nexus-video.service, restoring the original boot splash.
#
# Usage:
#   sudo ./uninstall.sh [--dry-run] [--backup-dir /path/to/backup]
#
# If --backup-dir is given, nexus-splash.service is restored from that backup.
# Otherwise the script restores a generic re-enable (the unit file is not
# changed, only its enabled state).
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=false
BACKUP_DIR=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --dry-run) DRY_RUN=true ;;
    --backup-dir=*) BACKUP_DIR="${1#--backup-dir=}" ;;
    --backup-dir) shift; BACKUP_DIR="${1:-}" ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
  shift
done

log()  { echo "[uninstall] $*"; }
die()  { echo "[uninstall] FATAL: $*" >&2; exit 1; }

run() {
  if $DRY_RUN; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

[[ $EUID -eq 0 ]] || die "Must run as root (sudo $0)"

# ── stop nexus-video if running ───────────────────────────────────────────────
if systemctl is-active --quiet nexus-video.service 2>/dev/null; then
  log "Stopping nexus-video.service..."
  run systemctl stop nexus-video.service
fi

# ── disable nexus-video ───────────────────────────────────────────────────────
if systemctl is-enabled --quiet nexus-video.service 2>/dev/null; then
  log "Disabling nexus-video.service..."
  run systemctl disable nexus-video.service
fi

# ── restore nexus-splash service file from backup (if available) ──────────────
if [[ -n "${BACKUP_DIR}" && -f "${BACKUP_DIR}/nexus-splash.service" ]]; then
  log "Restoring nexus-splash.service from backup ${BACKUP_DIR}..."
  run cp "${BACKUP_DIR}/nexus-splash.service" /etc/systemd/system/nexus-splash.service
fi

# ── remove nexus-video service unit ──────────────────────────────────────────
if [[ -f "/etc/systemd/system/nexus-video.service" ]]; then
  log "Removing /etc/systemd/system/nexus-video.service..."
  run rm /etc/systemd/system/nexus-video.service
fi

# ── re-enable nexus-splash ────────────────────────────────────────────────────
if [[ -f "/etc/systemd/system/nexus-splash.service" ]]; then
  log "Enabling nexus-splash.service..."
  run systemctl daemon-reload
  run systemctl enable nexus-splash.service
  log "nexus-splash.service re-enabled."
else
  log "nexus-splash.service unit not found — skipping re-enable."
  run systemctl daemon-reload
fi

if $DRY_RUN; then
  log "DRY RUN complete — no changes made."
else
  log "Uninstall complete!"
  log "  → nexus-video.service:  disabled and removed"
  log "  → nexus-splash.service: re-enabled"
  log "  → Changes take effect on NEXT BOOT (printer not rebooted)"
fi
