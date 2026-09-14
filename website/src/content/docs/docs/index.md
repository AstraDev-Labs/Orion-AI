---
title: Install Orion
description: Download and install Orion on Windows 10 or 11.
---

:::caution[Alpha software]
Orion is in alpha and has bugs. Please [report what breaks](https://github.com/AstraDev-Labs/Orion-AI/issues).
:::

## Before you start

- Windows 10 (version 1809 or later) or Windows 11, 64-bit.
- About **12 GB free** on the drive you install to.
- An internet connection for setup, which downloads the AI engine, a model and the voice.
- No administrator rights are needed. Orion installs for your user account only.

Not sure your PC is up to it? Use the [compatibility check](/system-requirements).

## Install

1. **Download** `OrionSetup-<version>.exe` from the [download page](/download) or [GitHub Releases](https://github.com/AstraDev-Labs/Orion-AI/releases).
2. **Run it.** Windows may show *"Windows protected your PC"*, because the alpha installer isn't code-signed yet. Choose **More info → Run anyway**.
3. **Accept the terms**, choose where to install (any drive with enough space), and pick features. Voice and screen understanding are optional.
4. Click **Install**. The installer copies the app, then Orion opens and finishes setting itself up.

## What setup installs

The first launch shows a setup screen with progress. It takes roughly 5 to 20 minutes depending on your connection. It installs, all inside the folder you chose:

| Component | Why |
| --- | --- |
| Python runtime (via uv) | Runs Orion's assistant server |
| Ollama | The local AI engine (skipped if you already have it) |
| A Qwen model sized to your RAM | Orion's brain |
| nomic-embed-text | Memory search |
| Whisper and Kokoro voice models | Speech recognition and the voice (if Voice is selected) |
| Moondream | Understanding your screen and camera (if selected) |
| Node.js | Only if WhatsApp is selected |

When it finishes, Orion greets you. If setup fails, see [Troubleshooting](/docs/troubleshooting).
