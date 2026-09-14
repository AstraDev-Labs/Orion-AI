---
title: Build from source
description: Run Orion from source, or build the Windows installer yourself.
---

## Requirements

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 for you)
- [Ollama](https://ollama.com)
- [Rust](https://rustup.rs) and [Node.js](https://nodejs.org) 20 or later, for the desktop app
- Git

## Run the assistant server

```bash
git clone https://github.com/AstraDev-Labs/Orion-AI.git
cd Orion-AI
uv sync --extra server --extra speech --extra speech-kokoro
ollama pull qwen3.5:4b
ollama pull nomic-embed-text
uv run orion serve
```

The server listens on `http://127.0.0.1:8000`.

## Run the desktop app

```bash
cd frontend
npm install
npm run tauri dev
```

## Run the tests

```bash
uv run pytest tests/
```

## Build the Windows installer

Needs [Inno Setup 6 or later](https://jrsoftware.org/isinfo.php).

```powershell
powershell -ExecutionPolicy Bypass -File installer\build-windows.ps1
```

The installer is written to `installer\dist`. To produce signed in-app updates, set `TAURI_SIGNING_PRIVATE_KEY` (and its password) before building; the script then writes the update manifest next to the installer. See `docs/desktop-auto-update.md` in the repository.
