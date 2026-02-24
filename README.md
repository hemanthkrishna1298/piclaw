# 🐾 PiClaw

**Plug-and-play AI agent box for Raspberry Pi.**

Pre-configured [PicoClaw](https://github.com/nichochar/picoclaw) on a Raspberry Pi — ready to run in minutes, no terminal required.

## What is this?


- ⚡ **Ready out of the box** — plug in power + ethernet, scan QR code, done
- 🤖 **Your own AI agent** — running 24/7 on hardware you own
- 🔒 **Private & local** — your data stays on your device

## How It Works

1. **Plug in** your PiClaw box (power + ethernet or WiFi)
2. **Scan the QR code** on the device
3. **Follow the setup wizard** (connect your AI provider, set your name)
4. **Done** — your AI agent is running

## What's Inside

- Raspberry Pi 5 (4GB)
- Pre-flashed SD card with PiClaw OS
- PicoClaw (lightweight Go-based AI agent runtime)
- Web-based setup wizard
- Auto-update system

## Tech Stack

- **Runtime:** [PicoClaw](https://github.com/nichochar/picoclaw) (Go binary, <1GB memory)
- **OS:** Raspberry Pi OS Lite (headless)
- **Setup:** Web-based onboarding wizard
- **Networking:** mDNS auto-discovery + WiFi setup via captive portal

## Status

🚧 **Early development** — Pi arrives Feb 26. First prototype coming soon.

## Interested?

Star this repo to follow progress. Questions? Open an issue.

---

Built by [@hemanthkrishna1298](https://github.com/hemanthkrishna1298)
