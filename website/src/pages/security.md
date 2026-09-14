---
layout: ../layouts/ProseLayout.astro
title: Security
description: How Orion keeps an AI assistant that can act on your computer under your control, and how to report a security problem.
eyebrow: Trust
---

# Security

An assistant that can send messages and change your computer has to be careful by default. This is how Orion stays under your control.

## Nothing irreversible without your yes

- **Drafts, not sends.** WhatsApp, Telegram, Discord and Slack messages, and emails, are queued as drafts. Orion shows you exactly what it will send, and it goes out only when *you* reply "yes".
- **The model can't approve itself.** Approvals come only from your own message. The AI is never given a way to approve its own queued actions.
- **Installs need approval too.** Before queueing an install, Orion resolves the exact package, checks its code signature and scans it with Microsoft Defender, then tells you about any concerns.
- **Only tools that fit the request.** A tool that changes something (away mode, volume, messaging) only runs when your request actually calls for it. A model can't slip in an unrelated action.
- **Dangerous actions are off.** Shutdown and restart are disabled, and the desktop-control tool refuses buttons like Send, Delete or Buy and banking or password windows.

## New tools are reviewed

When Orion writes a new tool for itself, the code is validated and run in a sandbox first, then queued for your approval. It's only saved and made available after you say yes.

## Local by default

- The assistant's server listens only on your own computer (127.0.0.1), and the Connections settings accept changes only from your own machine.
- Keys and tokens you save are stored locally in your profile, never in Orion's source or sent to Orion's developers.
- If you choose a cloud AI model, Orion strips recognisable personal details (emails, phone numbers) before sending.

## Genuine updates only

Orion checks GitHub for new versions. It installs an update only if the file carries a valid signature from the Orion release key built into the app. A tampered or unsigned file is refused and never run.

## Known limits (alpha)

- The Windows installer isn't code-signed yet, so Windows SmartScreen warns on first run.
- The WhatsApp feature uses an unofficial WhatsApp Web client (see the [terms](/terms)).
- This is alpha software: treat it accordingly, and don't connect accounts you can't afford to have misused by a bug.

## Reporting a vulnerability

Please report security problems privately through GitHub's **[private vulnerability reporting](https://github.com/AstraDev-Labs/Orion-AI/security/advisories/new)** rather than a public issue, with steps to reproduce. You'll get a reply as soon as possible.
