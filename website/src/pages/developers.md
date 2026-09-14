---
layout: ../layouts/ProseLayout.astro
title: Developers
description: Orion's architecture, tech stack and how to contribute. A Python agent runtime, a Rust core, and a Tauri desktop app.
eyebrow: Developers
---

# Developers

Orion is open source under the Apache License 2.0. The code, issues and releases live at [github.com/AstraDev-Labs/Orion-AI](https://github.com/AstraDev-Labs/Orion-AI).

## Architecture

| Layer | What it is |
| --- | --- |
| **Desktop app** | Tauri 2 (Rust) window with a React + Vite interface, the "Holotable" HUD. Manages the backend, tray, updates and setup progress. |
| **Agent server** | Python FastAPI server (`orion serve`) exposing an OpenAI-compatible chat API, speech endpoints and the HUD APIs. Listens on 127.0.0.1 only. |
| **Agents** | An orchestrator with native function calling, plus ReAct, CodeAct, research and scheduled agents. |
| **Tools** | 60+ tools (apps, media, system control, browser, memory, messaging, files, reminders, web), routed per request so small models see only relevant ones. |
| **Inference** | Ollama with Qwen 3.5 models by default; optional cloud engines behind a privacy scanner. |
| **Voice** | faster-whisper for speech recognition, Kokoro for the voice. Both local. |
| **Memory** | Dense vector memory with nomic-embed-text, plus a SQLite knowledge graph. |
| **Rust core** | `orion_rust` (PyO3), a compiled extension for performance-critical paths. |
| **Installer** | Inno Setup wrapper plus a PowerShell setup script that installs uv, Python, Ollama, models and voice per user. |

## Build and run from source

See [Build from source](/docs/build-from-source) in the docs. In short:

```bash
git clone https://github.com/AstraDev-Labs/Orion-AI.git
cd Orion-AI
uv sync --extra server --extra speech --extra speech-kokoro
uv run orion serve
```

Then run the desktop app from `frontend/` with `npm install` and `npm run tauri dev`.

## Contributing

- Read the [contributing guide](https://github.com/AstraDev-Labs/Orion-AI/blob/V1.0.1A/CONTRIBUTING.md) and the code of conduct.
- Good first steps: reproduce an open [issue](https://github.com/AstraDev-Labs/Orion-AI/issues), improve a tool, or add tests.
- Run the tests with `uv run pytest tests/`.
- Keep Orion local-first: no new network calls or data collection without a clear, user-visible reason.
