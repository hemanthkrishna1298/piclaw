#!/bin/bash
# PiClaw WiFi Setup — Captive Portal for Headless Configuration
#
# Flow:
# 1. On boot, check if WiFi is configured
# 2. If not, start AP mode (hostapd) with captive portal
# 3. User connects phone to "PiClaw-Setup" WiFi
# 4. Captive portal auto-opens → user enters home WiFi SSID/password
# 5. Pi connects to home WiFi → setup wizard becomes accessible
#
# Dependencies: hostapd, dnsmasq, python3
# Runs as: root (needs network control)

set -e

AP_SSID="PiClaw-Setup"
AP_INTERFACE="wlan0"
AP_IP="192.168.4.1"
AP_SUBNET="192.168.4.0/24"
DHCP_RANGE="192.168.4.10,192.168.4.50,24h"
PORTAL_PORT=80
WIFI_CONFIGURED_MARKER="/opt/piclaw/.wifi-configured"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [wifi-setup] $1" | tee -a /var/log/piclaw-wifi.log
}

check_wifi_connected() {
    # Check if wlan0 has an IP on a non-AP subnet
    local ip=$(ip addr show "$AP_INTERFACE" 2>/dev/null | grep "inet " | awk '{print $2}' | head -1)
    if [ -n "$ip" ] && [ "$ip" != "$AP_IP/24" ]; then
        return 0
    fi
    return 1
}

start_ap_mode() {
    log "Starting AP mode: $AP_SSID"

    # Stop any existing network management
    systemctl stop wpa_supplicant 2>/dev/null || true
    systemctl stop NetworkManager 2>/dev/null || true

    # Configure static IP for AP interface
    ip link set "$AP_INTERFACE" down
    ip addr flush dev "$AP_INTERFACE"
    ip addr add "$AP_IP/24" dev "$AP_INTERFACE"
    ip link set "$AP_INTERFACE" up

    # Write hostapd config
    cat > /tmp/piclaw-hostapd.conf <<EOF
interface=$AP_INTERFACE
driver=nl80211
ssid=$AP_SSID
hw_mode=g
channel=7
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
# Open network (no password) for easy onboarding
wpa=0
EOF

    # Write dnsmasq config — redirect ALL DNS to captive portal
    cat > /tmp/piclaw-dnsmasq.conf <<EOF
interface=$AP_INTERFACE
dhcp-range=$DHCP_RANGE
address=/#/$AP_IP
# Redirect all traffic to captive portal
no-resolv
log-queries
EOF

    # Start hostapd (access point)
    hostapd -B /tmp/piclaw-hostapd.conf
    log "hostapd started"

    # Start dnsmasq (DHCP + DNS redirect)
    dnsmasq -C /tmp/piclaw-dnsmasq.conf --pid-file=/tmp/piclaw-dnsmasq.pid
    log "dnsmasq started"

    # Enable IP forwarding for captive portal redirect
    echo 1 > /proc/sys/net/ipv4/ip_forward

    # Redirect all HTTP traffic to portal
    iptables -t nat -A PREROUTING -i "$AP_INTERFACE" -p tcp --dport 80 -j REDIRECT --to-port $PORTAL_PORT
    iptables -t nat -A PREROUTING -i "$AP_INTERFACE" -p tcp --dport 443 -j REDIRECT --to-port $PORTAL_PORT

    log "Captive portal active at http://$AP_IP"
}

stop_ap_mode() {
    log "Stopping AP mode..."
    killall hostapd 2>/dev/null || true
    kill $(cat /tmp/piclaw-dnsmasq.pid 2>/dev/null) 2>/dev/null || true
    iptables -t nat -F PREROUTING 2>/dev/null || true

    ip addr flush dev "$AP_INTERFACE"
    log "AP mode stopped"
}

connect_wifi() {
    local ssid="$1"
    local password="$2"
    local country="${3:-US}"

    log "Connecting to WiFi: $ssid"

    # Stop AP mode first
    stop_ap_mode

    # Set regulatory domain
    iw reg set "$country" 2>/dev/null || true

    # Write wpa_supplicant config
    cat > /etc/wpa_supplicant/wpa_supplicant-wlan0.conf <<EOF
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=$country

network={
    ssid="$ssid"
    psk="$password"
    key_mgmt=WPA-PSK
}
EOF
    chmod 600 /etc/wpa_supplicant/wpa_supplicant-wlan0.conf

    # Restart networking
    systemctl enable wpa_supplicant@wlan0
    systemctl restart wpa_supplicant@wlan0

    # Request IP via DHCP
    dhclient "$AP_INTERFACE" -timeout 15 2>/dev/null || dhcpcd "$AP_INTERFACE" 2>/dev/null || true

    # Wait for connection
    for i in $(seq 1 20); do
        if check_wifi_connected; then
            local new_ip=$(ip addr show "$AP_INTERFACE" | grep "inet " | awk '{print $2}' | head -1 | cut -d'/' -f1)
            log "Connected! IP: $new_ip"
            touch "$WIFI_CONFIGURED_MARKER"
            return 0
        fi
        sleep 1
    done

    log "ERROR: Failed to connect to $ssid"
    return 1
}

scan_wifi() {
    # Scan for available networks and return as JSON
    iw dev "$AP_INTERFACE" scan 2>/dev/null | \
        grep -E "SSID:|signal:" | \
        paste - - | \
        awk '{
            signal=$2;
            gsub(/.*SSID: /, "");
            ssid=$0;
            if (ssid != "" && ssid !~ /\\x00/) {
                printf "{\"ssid\":\"%s\",\"signal\":%s}\n", ssid, signal
            }
        }' | sort -t: -k2 -n | head -20
}

# --- Main ---
case "${1:-auto}" in
    auto)
        if [ -f "$WIFI_CONFIGURED_MARKER" ] && check_wifi_connected; then
            log "WiFi already configured and connected"
            exit 0
        fi

        if check_wifi_connected; then
            log "WiFi connected (ethernet/pre-configured)"
            touch "$WIFI_CONFIGURED_MARKER"
            exit 0
        fi

        # No WiFi — start captive portal
        start_ap_mode
        ;;
    connect)
        connect_wifi "$2" "$3" "${4:-US}"
        ;;
    scan)
        scan_wifi
        ;;
    stop)
        stop_ap_mode
        ;;
    *)
        echo "Usage: $0 {auto|connect <ssid> <password> [country]|scan|stop}"
        exit 1
        ;;
esac
