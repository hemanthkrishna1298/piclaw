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
OPT_DIRS = ["/opt/picoclaw/config", "/opt/picoclaw/workspace", "/opt/piclaw"]


@pytest.fixture(scope="session", autouse=True)
def setup_dirs():
    """Create required directories before tests."""
    for d in OPT_DIRS:
        os.makedirs(d, exist_ok=True)
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    yield
    # Cleanup after tests
    for f in ["/opt/picoclaw/config/picoclaw.json", "/opt/picoclaw/config/env", "/opt/piclaw/.setup-complete"]:
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
        env=env,
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

        # Verify config was created
        config_path = Path("/opt/picoclaw/config/picoclaw.json")
        assert config_path.exists(), "Config file should be created"
        config = json.loads(config_path.read_text())
        assert config["provider"] == "anthropic"
        assert config["model"] == "claude-sonnet-4-5"

        # Verify env file exists and has correct permissions
        env_path = Path("/opt/picoclaw/config/env")
        assert env_path.exists(), "Env file should be created"
        env_perms = oct(env_path.stat().st_mode)[-3:]
        assert env_perms == "600", f"Env file should be 600, got {env_perms}"
        env_content = env_path.read_text()
        assert "ANTHROPIC_API_KEY=sk-ant-test-key-123456" in env_content

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
