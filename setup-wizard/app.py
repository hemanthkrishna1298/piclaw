"""
PiClaw Setup Wizard
A simple web-based setup wizard for first-time PiClaw configuration.
Runs on port 8080 and guides users through connecting their AI provider.
"""

import json
import os
import subprocess
import socket
from pathlib import Path
from flask import Flask, render_template, request, jsonify, redirect, url_for

app = Flask(__name__)

CONFIG_DIR = Path("/opt/picoclaw/config")
CONFIG_FILE = CONFIG_DIR / "picoclaw.json"
WORKSPACE_DIR = Path("/opt/picoclaw/workspace")
SETUP_COMPLETE_MARKER = Path("/opt/piclaw/.setup-complete")

SUPPORTED_PROVIDERS = {
    "anthropic": {
        "name": "Anthropic (Claude)",
        "env_key": "ANTHROPIC_API_KEY",
        "default_model": "claude-sonnet-4-5",
        "docs_url": "https://console.anthropic.com/settings/keys",
    },
    "openai": {
        "name": "OpenAI (GPT)",
        "env_key": "OPENAI_API_KEY",
        "default_model": "gpt-4o",
        "docs_url": "https://platform.openai.com/api-keys",
    },
    "google": {
        "name": "Google (Gemini)",
        "env_key": "GOOGLE_API_KEY",
        "default_model": "gemini-2.5-flash",
        "docs_url": "https://aistudio.google.com/apikey",
    },
    "groq": {
        "name": "Groq",
        "env_key": "GROQ_API_KEY",
        "default_model": "llama-3.3-70b",
        "docs_url": "https://console.groq.com/keys",
    },
}


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
    }


@app.route("/")
def index():
    """Landing page — redirect to setup or dashboard."""
    if SETUP_COMPLETE_MARKER.exists():
        return redirect(url_for("dashboard"))
    return redirect(url_for("setup_step1"))


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
    """Step 3: Configure and start PicoClaw."""
    provider = request.form.get("provider")
    api_key = request.form.get("api_key")
    device_name = app.config.get("device_name", "piclaw")

    if not provider or not api_key:
        return redirect(url_for("setup_step2"))

    provider_info = SUPPORTED_PROVIDERS.get(provider)
    if not provider_info:
        return redirect(url_for("setup_step2"))

    # Create PicoClaw config
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    config = {
        "name": device_name,
        "provider": provider,
        "model": provider_info["default_model"],
    }

    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

    # Write environment file for systemd
    env_file = Path("/opt/picoclaw/config/env")
    with open(env_file, "w") as f:
        f.write(f'{provider_info["env_key"]}={api_key}\n')
    os.chmod(env_file, 0o600)

    # Run PicoClaw onboard
    try:
        env = os.environ.copy()
        env[provider_info["env_key"]] = api_key
        subprocess.run(
            ["/opt/picoclaw/picoclaw", "onboard", "--non-interactive",
             "--provider", provider, "--model", provider_info["default_model"]],
            env=env,
            timeout=30,
            capture_output=True,
        )
    except Exception as e:
        app.logger.error(f"PicoClaw onboard failed: {e}")

    # Enable and start PicoClaw service
    subprocess.run(["systemctl", "enable", "picoclaw.service"], capture_output=True)
    subprocess.run(["systemctl", "start", "picoclaw.service"], capture_output=True)

    # Mark setup complete
    SETUP_COMPLETE_MARKER.touch()

    return render_template("setup_complete.html", device=get_device_info(), config=config)


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
            config = json.load(f)

    return render_template(
        "dashboard.html",
        device=get_device_info(),
        config=config,
        status=picoclaw_status,
    )


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
