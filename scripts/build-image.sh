#!/bin/bash
# PiClaw Image Builder
# Creates a pre-configured Raspberry Pi OS image with PicoClaw installed
# Run on a Linux machine with root access

set -e

IMAGE_NAME="piclaw-$(date +%Y%m%d).img"
WORK_DIR="/tmp/piclaw-build"
MOUNT_DIR="$WORK_DIR/mount"
PI_OS_URL="https://downloads.raspberrypi.com/raspios_lite_arm64/images/raspios_lite_arm64-2026-01-13/2026-01-13-raspios-bookworm-arm64-lite.img.xz"

log() {
    echo "[BUILD] $1"
}

cleanup() {
    log "Cleaning up..."
    umount "$MOUNT_DIR/boot/firmware" 2>/dev/null || true
    umount "$MOUNT_DIR" 2>/dev/null || true
    losetup -d "$LOOP_DEV" 2>/dev/null || true
}
trap cleanup EXIT

# Check root
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Must run as root"
    exit 1
fi

mkdir -p "$WORK_DIR" "$MOUNT_DIR"

# 1. Download Raspberry Pi OS Lite (64-bit)
log "Downloading Raspberry Pi OS Lite..."
if [ ! -f "$WORK_DIR/raspios.img" ]; then
    curl -L "$PI_OS_URL" | xz -d > "$WORK_DIR/raspios.img"
fi

# 2. Expand image (add 500MB for PicoClaw + setup wizard)
log "Expanding image..."
cp "$WORK_DIR/raspios.img" "$WORK_DIR/$IMAGE_NAME"
truncate -s +500M "$WORK_DIR/$IMAGE_NAME"

# Expand partition
LOOP_DEV=$(losetup --find --show --partscan "$WORK_DIR/$IMAGE_NAME")
PART_NUM=2  # Root partition
parted -s "$LOOP_DEV" resizepart "$PART_NUM" 100%
e2fsck -f "${LOOP_DEV}p${PART_NUM}"
resize2fs "${LOOP_DEV}p${PART_NUM}"

# 3. Mount image
log "Mounting image..."
mount "${LOOP_DEV}p2" "$MOUNT_DIR"
mount "${LOOP_DEV}p1" "$MOUNT_DIR/boot/firmware"

# 4. Download PicoClaw ARM64 binary
log "Downloading PicoClaw..."
LATEST_URL=$(curl -s https://api.github.com/repos/sipeed/picoclaw/releases/latest \
    | grep "browser_download_url.*linux-arm64" \
    | head -1 \
    | cut -d '"' -f 4)
mkdir -p "$MOUNT_DIR/opt/picoclaw"
curl -L -o "$MOUNT_DIR/opt/picoclaw/picoclaw" "$LATEST_URL"
chmod +x "$MOUNT_DIR/opt/picoclaw/picoclaw"

# 5. Copy PiClaw files
log "Installing PiClaw..."
mkdir -p "$MOUNT_DIR/opt/piclaw"
cp -r "$(dirname "$0")/../scripts" "$MOUNT_DIR/opt/piclaw/"
cp -r "$(dirname "$0")/../setup-wizard" "$MOUNT_DIR/opt/piclaw/"
cp -r "$(dirname "$0")/../config" "$MOUNT_DIR/opt/piclaw/"
chmod +x "$MOUNT_DIR/opt/piclaw/scripts/"*.sh

# 6. Install systemd services
cp "$(dirname "$0")/../config/piclaw-first-boot.service" \
    "$MOUNT_DIR/etc/systemd/system/"
cp "$(dirname "$0")/../config/piclaw-setup-wizard.service" \
    "$MOUNT_DIR/etc/systemd/system/"
cp "$(dirname "$0")/../config/picoclaw.service" \
    "$MOUNT_DIR/etc/systemd/system/"

# Enable first-boot service
ln -sf /etc/systemd/system/piclaw-first-boot.service \
    "$MOUNT_DIR/etc/systemd/system/multi-user.target.wants/piclaw-first-boot.service"

# 7. Enable SSH (for debugging, can be disabled via wizard)
touch "$MOUNT_DIR/boot/firmware/ssh"

# 8. Configure WiFi setup via captive portal (wpa_supplicant placeholder)
log "Configuring network..."
mkdir -p "$MOUNT_DIR/opt/piclaw/network"

# 9. Install Python deps for setup wizard (minimal)
log "Pre-installing setup wizard dependencies..."
cat > "$MOUNT_DIR/opt/piclaw/setup-wizard/requirements.txt" << 'EOF'
flask==3.1.0
EOF

# Create pip install script for first boot
cat > "$MOUNT_DIR/opt/piclaw/scripts/install-deps.sh" << 'DEPS'
#!/bin/bash
apt-get update -qq
apt-get install -y -qq python3-flask avahi-daemon avahi-utils
DEPS
chmod +x "$MOUNT_DIR/opt/piclaw/scripts/install-deps.sh"

# 10. Unmount and compress
log "Finalizing image..."
sync
umount "$MOUNT_DIR/boot/firmware"
umount "$MOUNT_DIR"
losetup -d "$LOOP_DEV"

log "Compressing image..."
xz -T0 "$WORK_DIR/$IMAGE_NAME"

log "=== Build complete ==="
log "Image: $WORK_DIR/${IMAGE_NAME}.xz"
log "Flash with: xzcat ${IMAGE_NAME}.xz | sudo dd of=/dev/sdX bs=4M status=progress"
