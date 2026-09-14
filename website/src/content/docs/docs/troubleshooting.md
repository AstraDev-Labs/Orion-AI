---
title: Troubleshooting
description: Fixes for common problems with installing and using Orion.
---

If none of this helps, [open an issue](https://github.com/AstraDev-Labs/Orion-AI/issues/new?labels=bug) with what you did, what happened, and your log files.

## Where the logs are

- **Setup log:** `setup.log` in the folder you installed Orion to (by default `%LOCALAPPDATA%\Programs\Orion`).
- **Your data and settings:** `%USERPROFILE%\.orion`.

## Installing

**"Windows protected your PC"**
The alpha installer isn't code-signed. Choose **More info → Run anyway**.

**Setup stops or fails partway**
- Check your internet connection and free space (about 12 GB), then reopen Orion. Setup continues where it stopped.
- Antivirus software can block the downloads. Allow Orion's install folder and try again.
- Look at the end of `setup.log` for the step that failed.

**It says there isn't enough space**
Uninstall, then install again and choose a folder on a drive with more space.

## Replies

**Replies are slow**
- The first reply after starting takes longer while the model loads. After that Orion keeps it loaded for 30 minutes.
- Close games, browsers with many tabs and other heavy apps.
- Plug in your laptop. Battery-saving modes slow the processor.
- On PCs with 8 GB of RAM or less, a smaller model is chosen automatically. Expect a few seconds per reply.

**"Rehearsal · no daemon" in the top bar**
The assistant server isn't running. Right-click the tray icon to see its status, or quit Orion and open it again.

## Voice {#voice}

**Orion doesn't hear me**
- Make sure **Auditory** is on (highlighted) in the top bar.
- Allow microphone access: **Settings → Privacy & security → Microphone** → let desktop apps use the microphone.
- Check the right input device is selected in **Settings → System → Sound → Input**.

**Orion writes a reply but doesn't speak**
- Check **Voice replies** is on in the Auditory panel.
- Check Windows volume and the output device, and that Orion isn't muted in the volume mixer.
- Voice needs the Voice feature. If you didn't select it during install, run the installer again and select it.

**Orion mishears me**
Speak close to the microphone in a quiet room, and pause before and after commands. See [Getting better recognition](/docs/voice#getting-better-recognition).

## Other

**A window pops up when I copy text**
That's the quick-actions panel. Turn it off in the tray menu: uncheck **Show actions when I copy text**.

**Orion keeps running after I close it**
That's by design, so reminders keep working. Use **Quit Orion** in the tray menu to stop it.
