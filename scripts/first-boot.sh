#!/bin/bash
# PiClaw First Boot Setup
# Runs once on first boot to initialize PicoClaw and start the setup wizard

set -e

PICLAW_DIR="/opt/piclaw"
PICOCLAW_DIR="/opt/picoclaw"
PICOCLAW_BIN="$PICOCLAW_DIR/picoclaw"
SETUP_WIZARD_DIR="$PICLAW_DIR/setup-wizard"
LOG_FILE="/var/log/piclaw-first-boot.log"
MARKER_FILE="/opt/piclaw/.first-boot-done"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Skip if already completed
if [ -f "$MARKER_FILE" ]; then
    log "First boot already completed. Skipping."
    exit 0
fi

log "=== PiClaw First Boot Starting ==="

# 1. Set hostname
log "Setting hostname to piclaw..."
hostnamectl set-hostname piclaw 2>/dev/null || hostname piclaw

# 2. Ensure PicoClaw binary is present and executable
if [ ! -f "$PICOCLAW_BIN" ]; then
    log "Downloading PicoClaw binary..."
    ARCH=$(uname -m)
    case "$ARCH" in
        aarch64|arm64) PICOCLAW_ARCH="linux-arm64" ;;
        x86_64)        PICOCLAW_ARCH="linux-amd64" ;;
        armv7l)        PICOCLAW_ARCH="linux-arm"    ;;
        *)             log "ERROR: Unsupported architecture: $ARCH"; exit 1 ;;
    esac

    LATEST_URL=$(curl -s https://api.github.com/repos/sipeed/picoclaw/releases/latest \
        | grep "browser_download_url.*${PICOCLAW_ARCH}" \
        | head -1 \
        | cut -d '"' -f 4)

    if [ -z "$LATEST_URL" ]; then
        log "ERROR: Could not find PicoClaw release for $PICOCLAW_ARCH"
        exit 1
    fi

    mkdir -p "$PICOCLAW_DIR"
    curl -L -o "$PICOCLAW_BIN" "$LATEST_URL"
    chmod +x "$PICOCLAW_BIN"
    log "PicoClaw downloaded: $PICOCLAW_BIN"
fi

# 3. Create picoclaw system user
if ! id picoclaw &>/dev/null; then
    useradd --system --home-dir "$PICOCLAW_DIR" --shell /usr/sbin/nologin picoclaw
    log "Created picoclaw system user"
fi

# 4. Set up directory structure
mkdir -p "$PICOCLAW_DIR/workspace"
mkdir -p "$PICOCLAW_DIR/config"
chown -R picoclaw:picoclaw "$PICOCLAW_DIR"

# 5. Enable and start the setup wizard
log "Starting PiClaw setup wizard..."
systemctl enable piclaw-setup-wizard.service
systemctl start piclaw-setup-wizard.service

# 6. Enable mDNS so device is discoverable as piclaw.local
if command -v avahi-daemon &>/dev/null; then
    systemctl enable avahi-daemon
    systemctl start avahi-daemon
    log "mDNS enabled: device reachable at piclaw.local"
fi

log "=== PiClaw First Boot Complete ==="
log "Setup wizard available at http://piclaw.local:8080"
touch "$MARKER_FILE"
