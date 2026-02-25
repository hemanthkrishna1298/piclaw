"""
PiClaw Setup Wizard
A simple web-based setup wizard for first-time PiClaw configuration.
Runs on port 8080 and guides users through connecting their AI provider.
"""

import json
import os
import subprocess
import socket
import urllib.request
import urllib.error
from pathlib import Path
from flask import Flask, render_template, request, jsonify, redirect, url_for

app = Flask(__name__)
app.config["TESTING"] = os.environ.get("PICLAW_TESTING", "").lower() in ("1", "true")

PICOCLAW_HOME = Path(os.environ.get("PICOCLAW_HOME", "/home/picoclaw/.picoclaw"))
CONFIG_FILE = PICOCLAW_HOME / "config.json"
WORKSPACE_DIR = PICOCLAW_HOME / "workspace"
SETUP_COMPLETE_MARKER = Path("/opt/piclaw/.setup-complete")

SUPPORTED_PROVIDERS = {
    "anthropic": {
        "name": "Anthropic (Claude)",
        "config_key": "anthropic",
        "default_model": "claude-sonnet-4-5",
        "docs_url": "https://console.anthropic.com/settings/keys",
        "validate_url": "https://api.anthropic.com/v1/messages",
        "validate_header": "x-api-key",
        "validate_extra_headers": {"anthropic-version": "2023-06-01"},
    },
    "openai": {
        "name": "OpenAI (GPT)",
        "config_key": "openai",
        "default_model": "gpt-4o",
        "docs_url": "https://platform.openai.com/api-keys",
        "validate_url": "https://api.openai.com/v1/models",
        "validate_header": "Authorization",
        "validate_prefix": "Bearer ",
    },
    "gemini": {
        "name": "Google (Gemini)",
        "config_key": "gemini",
        "default_model": "gemini-2.5-flash",
        "docs_url": "https://aistudio.google.com/apikey",
        "validate_url": "https://generativelanguage.googleapis.com/v1beta/models",
        "validate_query": "key",
    },
    "groq": {
        "name": "Groq",
        "config_key": "groq",
        "default_model": "llama-3.3-70b",
        "docs_url": "https://console.groq.com/keys",
        "validate_url": "https://api.groq.com/openai/v1/models",
        "validate_header": "Authorization",
        "validate_prefix": "Bearer ",
    },
}


def validate_api_key(provider_key, api_key):
    """Validate an API key by making a lightweight request to the provider.

    Returns (is_valid: bool, error_message: str | None).
    We hit a read-only endpoint (list models) so we never incur usage costs.
    Timeout is aggressive (5s) since this runs during onboarding.
    """
    provider = SUPPORTED_PROVIDERS.get(provider_key)
    if not provider:
        return False, "Unknown provider"

    try:
        url = provider.get("validate_url", "")

        # Google Gemini uses query param auth instead of header
        if provider.get("validate_query"):
            url = f"{url}?{provider['validate_query']}={api_key}"

        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "PiClaw-Setup/1.0")

        # Header-based auth (Anthropic, OpenAI, Groq)
        if provider.get("validate_header"):
            prefix = provider.get("validate_prefix", "")
            req.add_header(provider["validate_header"], f"{prefix}{api_key}")

        # Extra headers (e.g., Anthropic version)
        for k, v in provider.get("validate_extra_headers", {}).items():
            req.add_header(k, v)

        resp = urllib.request.urlopen(req, timeout=5)
        # 2xx = valid key
        return True, None

    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "Invalid API key. Please check and try again."
        elif e.code == 403:
            return False, "API key doesn't have permission. Check your account."
        elif e.code == 429:
            # Rate limited but key IS valid
            return True, None
        else:
            return False, f"Provider returned error {e.code}. Try again."
    except urllib.error.URLError:
        return False, "Can't reach the provider. Check your internet connection."
    except Exception as e:
        return False, f"Validation failed: {str(e)}"


WIFI_SCRIPT = Path("/opt/piclaw/scripts/wifi-setup.sh")
WIFI_CONFIGURED_MARKER = Path("/opt/piclaw/.wifi-configured")


def get_device_info():
    """Gather basic device information."""
    hostname = socket.gethostname()
    ip_addr = "unknown"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_addr = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    return {
        "hostname": hostname,
        "ip": ip_addr,
        "setup_complete": SETUP_COMPLETE_MARKER.exists(),
        "wifi_configured": WIFI_CONFIGURED_MARKER.exists(),
    }


@app.route("/")
def index():
    """Landing page — redirect to WiFi setup, device setup, or dashboard."""
    if SETUP_COMPLETE_MARKER.exists():
        return redirect(url_for("dashboard"))
    # If WiFi isn't configured and we're in AP mode, show WiFi setup first
    if not WIFI_CONFIGURED_MARKER.exists() and _is_ap_mode():
        return redirect(url_for("wifi_setup"))
    return redirect(url_for("setup_step1"))


def _is_ap_mode():
    """Check if we're currently running as an access point.

    In AP mode the wifi-setup.sh script assigns 192.168.4.1 to wlan0.
    If the WIFI_SCRIPT doesn't exist (e.g. dev/testing on EC2), assume
    we're NOT in AP mode so the wizard flow skips the WiFi step.
    """
    if not WIFI_SCRIPT.exists():
        return False
    try:
        result = subprocess.run(
            ["ip", "addr", "show", "wlan0"],
            capture_output=True, text=True, timeout=3,
        )
        return "192.168.4.1" in result.stdout
    except Exception:
        return False


@app.route("/wifi", methods=["GET"])
def wifi_setup():
    """WiFi configuration page — shown when Pi is in AP mode."""
    return render_template("wifi_setup.html", device=get_device_info())


@app.route("/api/wifi/scan", methods=["POST"])
def api_wifi_scan():
    """Scan for available WiFi networks. Returns JSON list of SSIDs."""
    if not WIFI_SCRIPT.exists():
        return jsonify({"networks": [], "error": "WiFi setup not available on this device."})

    try:
        result = subprocess.run(
            ["bash", str(WIFI_SCRIPT), "scan"],
            capture_output=True, text=True, timeout=15,
        )
        networks = []
        seen = set()
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                net = json.loads(line)
                ssid = net.get("ssid", "").strip()
                if ssid and ssid not in seen:
                    seen.add(ssid)
                    networks.append(net)
            except json.JSONDecodeError:
                continue
        return jsonify({"networks": networks})
    except subprocess.TimeoutExpired:
        return jsonify({"networks": [], "error": "WiFi scan timed out. Try again."})
    except Exception as e:
        return jsonify({"networks": [], "error": str(e)})


@app.route("/api/wifi/connect", methods=["POST"])
def api_wifi_connect():
    """Connect to a WiFi network. Expects JSON with ssid, password, country."""
    data = request.get_json() or {}
    ssid = data.get("ssid", "").strip()
    password = data.get("password", "")
    country = data.get("country", "US").strip().upper()

    if not ssid:
        return jsonify({"success": False, "error": "SSID is required."})
    if not password:
        return jsonify({"success": False, "error": "Password is required."})

    if not WIFI_SCRIPT.exists():
        return jsonify({"success": False, "error": "WiFi setup not available on this device."})

    try:
        result = subprocess.run(
            ["bash", str(WIFI_SCRIPT), "connect", ssid, password, country],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            # Get the new IP so the user knows where to find the wizard
            new_ip = "unknown"
            try:
                ip_result = subprocess.run(
                    ["ip", "addr", "show", "wlan0"],
                    capture_output=True, text=True, timeout=3,
                )
                for line in ip_result.stdout.split("\n"):
                    if "inet " in line and "192.168.4." not in line:
                        new_ip = line.strip().split()[1].split("/")[0]
                        break
            except Exception:
                pass

            return jsonify({
                "success": True,
                "ip": new_ip,
                "message": f"Connected to {ssid}! Your PiClaw is now at http://{new_ip}:8080",
            })
        else:
            return jsonify({
                "success": False,
                "error": "Could not connect. Check your password and try again.",
            })
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Connection timed out. Try again."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/setup/1", methods=["GET"])
def setup_step1():
    """Step 1: Welcome + device name."""
    return render_template("setup_step1.html", device=get_device_info())


@app.route("/setup/2", methods=["GET", "POST"])
def setup_step2():
    """Step 2: Choose AI provider + enter API key."""
    if request.method == "POST":
        device_name = request.form.get("device_name", "piclaw")
        # Save device name for later
        app.config["device_name"] = device_name

    return render_template(
        "setup_step2.html",
        providers=SUPPORTED_PROVIDERS,
        device=get_device_info(),
    )


@app.route("/setup/3", methods=["POST"])
def setup_step3():
    """Step 3: Validate key, configure and start PicoClaw."""
    provider = request.form.get("provider")
    api_key = request.form.get("api_key", "").strip()
    device_name = app.config.get("device_name", "piclaw")

    if not provider or not api_key:
        return redirect(url_for("setup_step2"))

    provider_info = SUPPORTED_PROVIDERS.get(provider)
    if not provider_info:
        return redirect(url_for("setup_step2"))

    # Validate the API key before saving (skip in test mode)
    if not app.config.get("TESTING"):
        is_valid, error_msg = validate_api_key(provider, api_key)
        if not is_valid:
            return render_template(
                "setup_step2.html",
                providers=SUPPORTED_PROVIDERS,
                device=get_device_info(),
                error=error_msg,
                selected_provider=provider,
            )

    # Create PicoClaw config in its native format
    PICOCLAW_HOME.mkdir(parents=True, exist_ok=True)
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    # Read existing config template or create from scratch
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            config = json.load(f)
    else:
        config = {
            "agents": {
                "defaults": {
                    "workspace": str(WORKSPACE_DIR),
                    "restrict_to_workspace": True,
                    "provider": provider_info["config_key"],
                    "model": provider_info["default_model"],
                    "max_tokens": 8192,
                    "temperature": 0.7,
                    "max_tool_iterations": 20,
                }
            },
            "channels": {
                "telegram": {"enabled": False, "token": "", "allow_from": []},
            },
            "providers": {},
            "gateway": {"host": "0.0.0.0", "port": 18790},
            "tools": {
                "web": {
                    "duckduckgo": {"enabled": True, "max_results": 5},
                }
            },
            "heartbeat": {"enabled": True, "interval": 30},
        }

    # Set the provider and API key
    config["agents"]["defaults"]["provider"] = provider_info["config_key"]
    config["agents"]["defaults"]["model"] = provider_info["default_model"]

    if "providers" not in config:
        config["providers"] = {}
    config["providers"][provider_info["config_key"]] = {
        "api_key": api_key,
        "api_base": "",
    }

    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    os.chmod(CONFIG_FILE, 0o600)

    # Store display config for the completion page
    display_config = {
        "name": device_name,
        "provider": provider_info["name"],
        "model": provider_info["default_model"],
    }

    # Enable and start PicoClaw service
    subprocess.run(["systemctl", "enable", "picoclaw.service"], capture_output=True)
    subprocess.run(["systemctl", "start", "picoclaw.service"], capture_output=True)

    # Mark setup complete
    SETUP_COMPLETE_MARKER.touch()

    return render_template("setup_complete.html", device=get_device_info(), config=display_config)


@app.route("/dashboard")
def dashboard():
    """Post-setup dashboard showing PicoClaw status."""
    picoclaw_status = "unknown"
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "picoclaw.service"],
            capture_output=True, text=True, timeout=5,
        )
        picoclaw_status = result.stdout.strip()
    except Exception:
        pass

    config = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            raw = json.load(f)
            config = {
                "provider": raw.get("agents", {}).get("defaults", {}).get("provider", "N/A"),
                "model": raw.get("agents", {}).get("defaults", {}).get("model", "N/A"),
            }

    return render_template(
        "dashboard.html",
        device=get_device_info(),
        config=config,
        status=picoclaw_status,
    )


@app.route("/api/validate-key", methods=["POST"])
def api_validate_key():
    """AJAX endpoint to validate an API key without submitting the form."""
    data = request.get_json() or {}
    provider = data.get("provider", "")
    api_key = data.get("api_key", "").strip()

    if not provider or not api_key:
        return jsonify({"valid": False, "error": "Provider and API key are required."})

    is_valid, error_msg = validate_api_key(provider, api_key)
    return jsonify({"valid": is_valid, "error": error_msg})


@app.route("/api/status")
def api_status():
    """API endpoint for device status."""
    return jsonify({
        "device": get_device_info(),
        "picoclaw": {
            "installed": Path("/opt/picoclaw/picoclaw").exists(),
            "config": CONFIG_FILE.exists(),
            "setup_complete": SETUP_COMPLETE_MARKER.exists(),
        },
    })


@app.route("/api/restart", methods=["POST"])
def api_restart():
    """Restart PicoClaw service."""
    try:
        subprocess.run(["systemctl", "restart", "picoclaw.service"],
                       capture_output=True, timeout=10)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("FLASK_RUN_PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
