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
        aarch64|arm64) PICOCLAW_ARCH="Linux_arm64" ;;
        x86_64)        PICOCLAW_ARCH="Linux_x86_64" ;;
        armv7l|armv6l) PICOCLAW_ARCH="Linux_armv6"  ;;
        riscv64)       PICOCLAW_ARCH="Linux_riscv64" ;;
        *)             log "ERROR: Unsupported architecture: $ARCH"; exit 1 ;;
    esac

    LATEST_TAG=$(curl -s https://api.github.com/repos/sipeed/picoclaw/releases/latest \
        | grep '"tag_name"' | head -1 | cut -d '"' -f 4)
    LATEST_URL="https://github.com/sipeed/picoclaw/releases/download/${LATEST_TAG}/picoclaw_${LATEST_TAG#v}_${PICOCLAW_ARCH}.tar.gz"

    if [ -z "$LATEST_TAG" ]; then
        log "ERROR: Could not find PicoClaw latest release"
        exit 1
    fi

    mkdir -p "$PICOCLAW_DIR"
    curl -L "$LATEST_URL" | tar xz -C "$PICOCLAW_DIR"
    chmod +x "$PICOCLAW_DIR/picoclaw"
    log "PicoClaw $LATEST_TAG downloaded: $PICOCLAW_BIN"
fi

# 3. Create picoclaw system user with home directory
if ! id picoclaw &>/dev/null; then
    useradd --system --home-dir /home/picoclaw --create-home --shell /usr/sbin/nologin picoclaw
    log "Created picoclaw system user"
fi

# 4. Set up directory structure
mkdir -p /home/picoclaw/.picoclaw/workspace
chown -R picoclaw:picoclaw /home/picoclaw
chown -R picoclaw:picoclaw "$PICOCLAW_DIR"

# 5. Run picoclaw onboard as picoclaw user to generate default config
sudo -u picoclaw "$PICOCLAW_BIN" onboard
log "PicoClaw onboard complete"

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
