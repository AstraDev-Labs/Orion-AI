---
layout: ../layouts/ProseLayout.astro
title: Privacy policy
description: How Orion handles your data. It runs on your own computer, has no accounts, and sends no usage analytics.
eyebrow: Legal
updated: 14 September 2026
---

# Privacy policy

Orion is local-first. It has no accounts, sends no usage analytics, and processes your conversations on your own computer by default. This page explains what stays on your PC, what goes online and when, and what this website collects.

## What stays on your computer

- **Your conversations, memories, notes and settings**, and the keys and tokens you save for connected services, are stored in the `.orion` folder in your Windows user profile.
- **The AI engine, models and Orion's runtime** are stored in the folder you choose during setup.
- **Speech recognition, the voice, and screen or camera understanding** run locally. Orion uses the microphone, camera or screen only when you use those features.

## What goes over the internet, and when

- **During setup:** Orion's components are downloaded from their publishers: ollama.com (AI engine and models), astral.sh and GitHub (uv and Python), pypi.org (Python packages), huggingface.co (voice models), nodejs.org (Node.js, only with WhatsApp) and Microsoft (WebView2, only if missing). Those sites receive ordinary download requests, including your IP address.
- **Update checks:** Orion reads a public version file from GitHub every few hours. No personal data is sent. You can turn this off in the tray menu ("Check for updates automatically").
- **When you ask for it:** web searches send your search words to the search provider (DuckDuckGo, or Tavily if you add a Tavily key); weather requests send the place name to Open-Meteo; opening web pages, videos or music contacts those sites.
- **Services you connect:** when you link email, WhatsApp, Telegram, Discord, Slack or another service, the content you choose to send or receive goes through that service.
- **Cloud AI (optional):** if you add an API key for a cloud AI provider and choose one of its models, your messages for those conversations are sent to that provider. By default Orion first removes personal details it can recognise, such as email addresses and phone numbers. Nothing is sent to a cloud AI unless you set this up.

## What Orion does not do

- No analytics or usage tracking. No advertising. No selling or sharing of your data.
- No Orion account, and no Orion servers that receive your conversations.

## Your control

- You can ask Orion to show or forget what it remembers about you, and disconnect any connected account from the Connections screen.
- When you uninstall, you choose what is removed, including your settings, memories and conversations.

## This website

- The site has **no cookies, no analytics and no trackers**.
- The download and release details are loaded by your browser straight from **GitHub's public API** (api.github.com), and the installer downloads from GitHub. GitHub receives those requests under [its own privacy statement](https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement).
- The PC compatibility check runs **only in your browser**. Nothing it reads is sent anywhere.
- The site is hosted on GitHub Pages, which may keep standard server logs.

## Changes and contact

This policy may change with new versions of Orion; the current version ships with every install as *Terms and Privacy.txt*. Questions or concerns: [open an issue on GitHub](https://github.com/AstraDev-Labs/Orion-AI/issues).
