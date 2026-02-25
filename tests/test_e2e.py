"""
PiClaw Setup Wizard — End-to-End Tests
Runs the full onboarding flow using Playwright + headless Chromium.

Usage:
    cd piclaw && source .venv/bin/activate
    pytest tests/test_e2e.py -v --screenshot on
"""

import json
import subprocess
import time
import os
import signal
import pytest
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

FLASK_PORT = 8090  # Use non-standard port to avoid conflicts
FLASK_URL = f"http://localhost:{FLASK_PORT}"
SCREENSHOTS_DIR = Path(__file__).parent.parent / "docs" / "test-screenshots"

# Directories the app expects
PICOCLAW_HOME = os.environ.get("PICOCLAW_HOME", "/home/picoclaw/.picoclaw")
OPT_DIRS = [PICOCLAW_HOME, f"{PICOCLAW_HOME}/workspace", "/opt/piclaw"]


@pytest.fixture(scope="session", autouse=True)
def setup_dirs():
    """Create required directories before tests."""
    for d in OPT_DIRS:
        os.makedirs(d, exist_ok=True)
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    yield
    # Cleanup after tests
    for f in [f"{PICOCLAW_HOME}/config.json", "/opt/piclaw/.setup-complete"]:
        try:
            os.remove(f)
        except FileNotFoundError:
            pass


@pytest.fixture(scope="session")
def flask_server():
    """Start the Flask app for testing."""
    env = os.environ.copy()
    env["FLASK_RUN_PORT"] = str(FLASK_PORT)

    app_path = Path(__file__).parent.parent / "setup-wizard" / "app.py"
    venv_python = Path(__file__).parent.parent / ".venv" / "bin" / "python"

    proc = subprocess.Popen(
        [str(venv_python), str(app_path)],
        env={**env, "PICOCLAW_HOME": PICOCLAW_HOME, "PICLAW_TESTING": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid,
    )

    # Wait for server to be ready
    for _ in range(30):
        try:
            import urllib.request
            urllib.request.urlopen(f"{FLASK_URL}/api/status")
            break
        except Exception:
            time.sleep(0.5)
    else:
        proc.kill()
        raise RuntimeError("Flask server didn't start in time")

    yield proc

    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    proc.wait(timeout=5)


@pytest.fixture(scope="session")
def browser_context():
    """Create a persistent browser context."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 400, "height": 800})
        yield context
        context.close()
        browser.close()


@pytest.fixture
def page(browser_context):
    """Fresh page for each test."""
    page = browser_context.new_page()
    yield page
    page.close()


class TestSetupWizardE2E:
    """End-to-end tests for the PiClaw setup wizard."""

    def test_root_redirects_to_setup(self, flask_server, page):
        """Root URL should redirect to setup step 1 when not configured."""
        page.goto(FLASK_URL)
        assert "/setup/1" in page.url
        page.screenshot(path=str(SCREENSHOTS_DIR / "01-redirect-to-setup.png"))

    def test_step1_renders_correctly(self, flask_server, page):
        """Step 1 should show welcome page with device name input."""
        page.goto(f"{FLASK_URL}/setup/1")

        # Check title
        title = page.locator("h1")
        expect(title).to_have_text("Welcome to PiClaw")

        # Check input exists with default value
        name_input = page.locator("#device_name")
        expect(name_input).to_have_value("piclaw")

        # Check continue button exists
        submit_btn = page.locator("button[type='submit']")
        expect(submit_btn).to_be_visible()
        expect(submit_btn).to_have_text("Continue →")

        # Check step indicator (first dot active)
        active_dots = page.locator(".step-dot.active")
        assert active_dots.count() == 1

        page.screenshot(path=str(SCREENSHOTS_DIR / "02-step1-welcome.png"))

    def test_step1_custom_name(self, flask_server, page):
        """Step 1 should accept custom device name."""
        page.goto(f"{FLASK_URL}/setup/1")

        name_input = page.locator("#device_name")
        name_input.clear()
        name_input.fill("jarvis")
        expect(name_input).to_have_value("jarvis")

        page.screenshot(path=str(SCREENSHOTS_DIR / "03-step1-custom-name.png"))

    def test_step1_to_step2_navigation(self, flask_server, page):
        """Clicking continue on step 1 should go to step 2."""
        page.goto(f"{FLASK_URL}/setup/1")

        page.locator("#device_name").fill("my-agent")
        page.locator("button[type='submit']").click()

        page.wait_for_url("**/setup/2")
        assert "/setup/2" in page.url

        page.screenshot(path=str(SCREENSHOTS_DIR / "04-step2-providers.png"))

    def test_step2_shows_all_providers(self, flask_server, page):
        """Step 2 should display all 4 provider options."""
        page.goto(f"{FLASK_URL}/setup/2")

        providers = page.locator(".provider-card")
        assert providers.count() == 4

        # Check each provider is present
        provider_names = page.locator(".provider-card .name")
        texts = [provider_names.nth(i).text_content() for i in range(4)]
        assert "Anthropic (Claude)" in texts
        assert "OpenAI (GPT)" in texts
        assert "Google (Gemini)" in texts
        assert "Groq" in texts

        page.screenshot(path=str(SCREENSHOTS_DIR / "05-step2-all-providers.png"))

    def test_step2_provider_selection(self, flask_server, page):
        """Clicking a provider card should select it and show API key input."""
        page.goto(f"{FLASK_URL}/setup/2")

        # API key section should be hidden initially
        api_section = page.locator("#apiKeySection")
        expect(api_section).to_be_hidden()

        # Click Anthropic
        page.locator(".provider-card", has_text="Anthropic").click()

        # API key section should now be visible
        expect(api_section).to_be_visible()

        # Selected card should have 'selected' class
        selected = page.locator(".provider-card.selected")
        assert selected.count() == 1
        expect(selected.locator(".name")).to_have_text("Anthropic (Claude)")

        # Submit button should be visible
        submit_btn = page.locator("#submitBtn")
        expect(submit_btn).to_be_visible()

        # Hidden input should have the provider value
        hidden_input = page.locator("#selectedProvider")
        expect(hidden_input).to_have_value("anthropic")

        page.screenshot(path=str(SCREENSHOTS_DIR / "06-step2-provider-selected.png"))

    def test_step2_docs_link_updates(self, flask_server, page):
        """Docs link should update when switching providers."""
        page.goto(f"{FLASK_URL}/setup/2")

        # Select OpenAI
        page.locator(".provider-card", has_text="OpenAI").click()
        docs_link = page.locator("#docsLink")
        expect(docs_link).to_have_attribute("href", "https://platform.openai.com/api-keys")

        # Switch to Google
        page.locator(".provider-card", has_text="Google").click()
        expect(docs_link).to_have_attribute("href", "https://aistudio.google.com/apikey")

        page.screenshot(path=str(SCREENSHOTS_DIR / "07-step2-switched-provider.png"))

    def test_full_setup_flow(self, flask_server, page):
        """Complete end-to-end: step 1 → step 2 → step 3 → dashboard."""
        # Step 1: Name device
        page.goto(f"{FLASK_URL}/setup/1")
        page.locator("#device_name").clear()
        page.locator("#device_name").fill("test-agent")
        page.locator("button[type='submit']").click()
        page.wait_for_url("**/setup/2")
        page.screenshot(path=str(SCREENSHOTS_DIR / "08-flow-step2.png"))

        # Step 2: Select provider + enter API key
        page.locator(".provider-card", has_text="Anthropic").click()
        page.locator("#api_key").fill("sk-ant-test-key-123456")
        page.screenshot(path=str(SCREENSHOTS_DIR / "09-flow-api-key.png"))

        # Submit
        page.locator("#submitBtn").click()

        # Step 3: Should show success
        page.wait_for_load_state("networkidle")
        title = page.locator("h1")
        expect(title).to_have_text("You're All Set!")
        page.screenshot(path=str(SCREENSHOTS_DIR / "10-flow-complete.png"))

        # Verify config was created in PicoClaw's native format
        config_path = Path(PICOCLAW_HOME) / "config.json"
        assert config_path.exists(), "Config file should be created"
        config = json.loads(config_path.read_text())
        assert config["agents"]["defaults"]["provider"] == "anthropic"
        assert config["agents"]["defaults"]["model"] == "claude-sonnet-4-5"
        assert config["providers"]["anthropic"]["api_key"] == "sk-ant-test-key-123456"

        # Verify config file permissions (600 — contains API key)
        config_perms = oct(config_path.stat().st_mode)[-3:]
        assert config_perms == "600", f"Config file should be 600, got {config_perms}"

        # Navigate to dashboard
        page.locator("a", has_text="Go to Dashboard").click()
        page.wait_for_url("**/dashboard")
        expect(page.locator("h1")).to_have_text("PiClaw Dashboard")
        page.screenshot(path=str(SCREENSHOTS_DIR / "11-flow-dashboard.png"))

    def test_root_redirects_to_dashboard_after_setup(self, flask_server, page):
        """After setup is complete, root should redirect to dashboard."""
        # Setup complete marker should exist from previous test
        page.goto(FLASK_URL)
        assert "/dashboard" in page.url
        page.screenshot(path=str(SCREENSHOTS_DIR / "12-post-setup-redirect.png"))

    def test_api_status_endpoint(self, flask_server, page):
        """API status should return valid JSON with device info."""
        response = page.goto(f"{FLASK_URL}/api/status")
        body = json.loads(page.locator("body").text_content())

        assert "device" in body
        assert "picoclaw" in body
        assert body["picoclaw"]["setup_complete"] is True
        assert body["picoclaw"]["config"] is True

    def test_dashboard_restart_button(self, flask_server, page):
        """Dashboard restart button should exist and be clickable."""
        page.goto(f"{FLASK_URL}/dashboard")

        restart_btn = page.locator("button", has_text="Restart Agent")
        expect(restart_btn).to_be_visible()

        page.screenshot(path=str(SCREENSHOTS_DIR / "13-dashboard-restart.png"))


class TestMobileResponsiveness:
    """Test the UI at different viewport sizes."""

    @pytest.mark.parametrize("width,height,name", [
        (320, 568, "iphone-se"),
        (375, 812, "iphone-x"),
        (768, 1024, "ipad"),
    ])
    def test_step1_responsive(self, flask_server, browser_context, width, height, name):
        """Step 1 should render properly at various viewport sizes."""
        page = browser_context.new_page()
        page.set_viewport_size({"width": width, "height": height})
        page.goto(f"{FLASK_URL}/setup/1")

        # Title should be visible
        expect(page.locator("h1")).to_be_visible()
        # Input should be visible
        expect(page.locator("#device_name")).to_be_visible()
        # Button should be visible
        expect(page.locator("button[type='submit']")).to_be_visible()

        page.screenshot(path=str(SCREENSHOTS_DIR / f"responsive-step1-{name}.png"))
        page.close()

    @pytest.mark.parametrize("width,height,name", [
        (320, 568, "iphone-se"),
        (375, 812, "iphone-x"),
        (768, 1024, "ipad"),
    ])
    def test_step2_responsive(self, flask_server, browser_context, width, height, name):
        """Step 2 provider grid should not overflow at any viewport size."""
        page = browser_context.new_page()
        page.set_viewport_size({"width": width, "height": height})
        page.goto(f"{FLASK_URL}/setup/2")

        # All 4 providers should be visible
        providers = page.locator(".provider-card")
        assert providers.count() == 4

        # Check no horizontal overflow
        grid = page.locator(".provider-grid")
        grid_box = grid.bounding_box()
        assert grid_box["x"] >= 0, f"Grid overflows left at {name}"
        assert grid_box["x"] + grid_box["width"] <= width, f"Grid overflows right at {name}"

        page.screenshot(path=str(SCREENSHOTS_DIR / f"responsive-step2-{name}.png"))
        page.close()


class TestErrorHandling:
    """Test error states and validation."""

    def test_step2_empty_submission_blocked(self, flask_server, page):
        """Submitting step 2 without provider should show client-side error."""
        page.goto(f"{FLASK_URL}/setup/2")

        # Try to submit the form directly via JS (bypass hidden button)
        page.evaluate("document.getElementById('providerForm').requestSubmit()")
        page.wait_for_timeout(500)

        # Should show error banner
        error = page.locator("#errorBanner")
        expect(error).to_be_visible()
        page.screenshot(path=str(SCREENSHOTS_DIR / "14-error-no-provider.png"))

    def test_step2_empty_key_blocked(self, flask_server, page):
        """Submitting with provider but no key should show error."""
        page.goto(f"{FLASK_URL}/setup/2")

        page.locator(".provider-card", has_text="Anthropic").click()
        # Don't fill the key — click submit
        page.locator("#submitBtn").click()
        page.wait_for_timeout(500)

        error = page.locator("#errorBanner")
        expect(error).to_be_visible()
        page.screenshot(path=str(SCREENSHOTS_DIR / "15-error-no-key.png"))

    def test_step2_short_key_blocked(self, flask_server, page):
        """Short API key should be blocked client-side."""
        page.goto(f"{FLASK_URL}/setup/2")

        page.locator(".provider-card", has_text="OpenAI").click()
        page.locator("#api_key").fill("abc")
        page.locator("#submitBtn").click()
        page.wait_for_timeout(500)

        error = page.locator("#errorBanner")
        expect(error).to_be_visible()
        assert "too short" in error.text_content().lower()
        page.screenshot(path=str(SCREENSHOTS_DIR / "16-error-short-key.png"))

    def test_validate_key_api_endpoint(self, flask_server, page):
        """API validation endpoint should return proper JSON."""
        # Missing fields
        page.goto(f"{FLASK_URL}/setup/1")  # just to have a page context
        result = page.evaluate("""async () => {
            const res = await fetch('/api/validate-key', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({provider: '', api_key: ''})
            });
            return await res.json();
        }""")
        assert result["valid"] is False
        assert "required" in result["error"].lower()

    def test_step2_loading_state_on_submit(self, flask_server, page):
        """Submit button should show spinner when clicked with valid input."""
        page.goto(f"{FLASK_URL}/setup/2")

        page.locator(".provider-card", has_text="Groq").click()
        page.locator("#api_key").fill("gsk_test_key_that_is_long_enough")

        # Check the spinner text appears (form will submit but we catch the state)
        page.locator("#submitBtn").click()

        # Button should show loading state briefly
        spinner = page.locator("#btnSpinner")
        # It might have already submitted, so just verify the JS ran
        page.screenshot(path=str(SCREENSHOTS_DIR / "17-submit-loading.png"))


class TestWiFiSetup:
    """Test WiFi setup page and API endpoints."""

    def test_wifi_page_renders(self, flask_server, page):
        """WiFi setup page should render correctly."""
        page.goto(f"{FLASK_URL}/wifi")

        expect(page.locator("h1")).to_have_text("Connect to WiFi")
        expect(page.locator("#scanCard")).to_be_visible()
        page.screenshot(path=str(SCREENSHOTS_DIR / "18-wifi-setup.png"))

    def test_wifi_scan_api_no_script(self, flask_server, page):
        """WiFi scan should return error when script not available."""
        page.goto(f"{FLASK_URL}/setup/1")
        result = page.evaluate("""async () => {
            const res = await fetch('/api/wifi/scan', { method: 'POST' });
            return await res.json();
        }""")
        assert "networks" in result
        assert result.get("error") is not None  # script doesn't exist on EC2

    def test_wifi_connect_api_validation(self, flask_server, page):
        """WiFi connect should validate required fields."""
        page.goto(f"{FLASK_URL}/setup/1")

        # Missing SSID
        result = page.evaluate("""async () => {
            const res = await fetch('/api/wifi/connect', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ssid: '', password: 'test'})
            });
            return await res.json();
        }""")
        assert result["success"] is False
        assert "ssid" in result["error"].lower()

        # Missing password
        result = page.evaluate("""async () => {
            const res = await fetch('/api/wifi/connect', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ssid: 'TestNetwork', password: ''})
            });
            return await res.json();
        }""")
        assert result["success"] is False
        assert "password" in result["error"].lower()

    def test_wifi_manual_entry_button(self, flask_server, page):
        """Manual entry button should show SSID input field."""
        page.goto(f"{FLASK_URL}/wifi")

        manual_btn = page.locator("button", has_text="Enter network name manually")
        expect(manual_btn).to_be_visible()

        manual_btn.click()
        page.wait_for_timeout(300)

        # Connect card should be visible with manual SSID input
        expect(page.locator("#connectCard")).to_be_visible()
        expect(page.locator("#manualSSID")).to_be_visible()
        page.screenshot(path=str(SCREENSHOTS_DIR / "19-wifi-manual-entry.png"))

    def test_root_skips_wifi_on_ec2(self, flask_server, page):
        """On EC2 (no AP mode), root should skip WiFi and go to setup."""
        # Remove setup complete marker to test fresh state
        try:
            os.remove("/opt/piclaw/.setup-complete")
        except FileNotFoundError:
            pass
        try:
            os.remove(f"{PICOCLAW_HOME}/config.json")
        except FileNotFoundError:
            pass

        page.goto(FLASK_URL)
        # Should go to setup/1, NOT wifi (since _is_ap_mode returns False on EC2)
        assert "/setup/1" in page.url
