---
layout: ../layouts/ProseLayout.astro
title: Changelog
description: What's new in each Orion release.
eyebrow: Changelog
---

# Changelog

Full release notes and every build are on [GitHub Releases](https://github.com/AstraDev-Labs/Orion-AI/releases).

## 1.0.1 alpha

The first public Windows installer.

### New
- **One-click Windows installer.** Installs the AI engine, a model sized to your PC's memory, speech recognition, the voice and optional features, into the folder you choose. No admin rights needed.
- **In-app updates.** Orion checks for new versions, notifies you, and installs signed updates itself.
- **Greeting on launch.** Orion says hello by name when you open it.
- **Voice replies for typed messages**, with a Voice replies switch in the Auditory panel.
- **Tray icon.** Orion keeps running in the tray when you close the window, with status, "Start with Windows" and quit.
- **Uninstall choices.** Pick what to remove, including models and your personal data.
- **Terms and privacy** shown and accepted during setup.

### Improved
- **Much faster replies.** The model stays loaded, prompts are smaller and tools are chosen per request. A time question dropped from 24 s to about 3 s on a laptop.
- **Better speech recognition.** English speech now uses the English Whisper model: far fewer misheard commands at the same speed.
- **Live weather** from Open-Meteo instead of search snippets.
- **All tools enabled** on a fresh install.

### Fixed
- Voice replies were silent in the desktop app.
- The interface could stay on an old version after an update.
- A clipboard window popped up on every copy (now off by default).
- A terminal window opened alongside the app.
- Quitting could leave the assistant server running.

### Privacy
- Usage analytics is **off, with no built-in endpoint**. Orion sends no usage data.
