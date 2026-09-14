# Desktop auto-update

## Windows installer builds (OrionSetup.exe)

Orion installed with the Windows installer updates itself. Tauri's updater
(below) cannot do this: it installs Tauri's NSIS/MSI bundles, a different
package without the bundled backend or setup step.

How it works (`frontend/src-tauri/src/app_update.rs`):

1. 90 seconds after launch, then every 6 hours, Orion reads
   `https://github.com/AstraDev-Labs/Orion-AI/releases/latest/download/orion-windows-update.json`
   (`{ version, notes, url, signature }`). Users can turn this off in the tray
   menu ("Check for updates automatically") or check by hand ("Check for updates").
2. If that version is newer, Orion shows a Windows notification, an
   "Update now" prompt in the app, and an "Update now" item in the tray menu.
3. "Update now" downloads the installer, verifies its minisign signature
   against `plugins.updater.pubkey` in `tauri.conf.json`, runs it with
   `/SILENT /UPDATE=1` and quits. The installer keeps the install folder and
   chosen features, reruns setup, then reopens Orion. A file whose signature
   does not match is never saved or run.

### Publishing an update

1. Bump the version in `frontend/src-tauri/tauri.conf.json` (and `Cargo.toml`).
2. Build with the signing key in the environment:

   ```powershell
   $env:TAURI_SIGNING_PRIVATE_KEY = Get-Content path\to\orion.key -Raw
   $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = '...'   # if the key has one
   powershell -ExecutionPolicy Bypass -File installer\build-windows.ps1 -ReleaseNotes "What changed"
   ```

   This writes `installer\dist\OrionSetup-<version>.exe`, its `.sig`, and
   `orion-windows-update.json`.
3. Create a GitHub release tagged `v<version>` on `AstraDev-Labs/Orion-AI` and
   upload all three files. Installed copies offer the update within 6 hours,
   or immediately from the tray's "Check for updates".

Without the signing key the build still makes an installer, but no update
package: installed apps only accept signed updates.

## Tauri updater (fallback for other builds)

The desktop app also includes [Tauri's updater
plugin](https://v2.tauri.app/plugin/updater/). `UpdateChecker.tsx` only uses
it when the Windows installer update path above is unavailable (for example a
development build), polling the endpoint in `tauri.conf.json` under
`plugins.updater.endpoints`.

No release currently publishes a Tauri `latest.json`, so this fallback finds
no update and stays silent. All public releases go through the Windows
installer flow above.

## How releases are made

Releases are built on a maintainer's machine, not in CI:

1. Build the installer (and, with the signing key, the update package) with
   `installer\build-windows.ps1`, as described in "Publishing an update".
2. Create a GitHub release tagged `v<version>` and attach
   `OrionSetup-<version>.exe`, its `.sig`, and `orion-windows-update.json`.
3. Publish it as a normal release, not a pre-release: installed copies read
   `releases/latest`, which skips pre-releases. The website's download button
   picks up the installer from the same release.

No GitHub Actions workflow builds or publishes releases; the workflows only
run checks.

## Signing

Updates are signed with a minisign key pair created by `tauri signer
generate`. The private key stays with the maintainer and is supplied at build
time through environment variables:

| Variable | Purpose |
|---|---|
| `TAURI_SIGNING_PRIVATE_KEY` | Private key contents |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | Passphrase for the private key, if it has one |

The matching public key is baked into the app at
`tauri.conf.json:plugins.updater.pubkey`. Never commit the private key. If
you ever rotate the key, replace the public key in the JSON file at the same
time: copies with the old public key reject updates signed by the new key and
must be reinstalled manually.

## Disabling the updater locally

For frontend development, set `VITE_OPENORION_NO_UPDATER=1` in your
shell before running `npm run tauri dev`. Vite injects any
`VITE_`-prefixed env var into `import.meta.env`, and the
`UpdateChecker.tsx` component honors it to skip the 30-minute poll.

```bash
export VITE_OPENORION_NO_UPDATER=1
npm run tauri dev
```

This is purely a dev escape hatch — it has no effect on production
builds (where `import.meta.env.VITE_OPENORION_NO_UPDATER` will be
`undefined` unless you explicitly set it at build time).

## Verifying a release manually

```bash
# Download the latest Windows update manifest and confirm it parses cleanly
curl -fsSL https://github.com/AstraDev-Labs/Orion-AI/releases/latest/download/orion-windows-update.json | jq .

# Fields:
#   version    — must match the release tag (without the leading "v")
#   notes      — release notes shown in the app
#   url        — download URL of OrionSetup-<version>.exe
#   signature  — base64 minisign signature of that installer
```

A 404 means the latest release has no `orion-windows-update.json` (it was
built without the signing key). Installed copies then simply see no update.
