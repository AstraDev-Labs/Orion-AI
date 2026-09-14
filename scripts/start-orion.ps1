<#
.SYNOPSIS
    Start Orion: Ollama + the backend, then open the installed PWA.

    Replaces the old Tauri desktop shell's launch role, minus the native
    wrapper -- the frontend is a real PWA (see frontend/vite.config.ts's
    VitePWA config) served directly by the backend
    (src/orion/server/app.py's static-file mount), installable from
    Chrome/Edge as a real standalone app. This script just makes sure the
    two real processes it depends on (Ollama, the Orion backend) are up
    before opening it, instead of the user having to start each by hand.
#>

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$appUrl = "http://127.0.0.1:8000"

function Test-Url($url, $timeoutSec = 1) {
    try {
        $resp = Invoke-WebRequest -Uri $url -TimeoutSec $timeoutSec -UseBasicParsing -ErrorAction Stop
        return $resp.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Wait-ForUrl($url, $label, $maxSeconds = 60) {
    $elapsed = 0
    while (-not (Test-Url $url)) {
        if ($elapsed -ge $maxSeconds) {
            Write-Host "Timed out waiting for $label at $url" -ForegroundColor Red
            exit 1
        }
        Start-Sleep -Seconds 1
        $elapsed += 1
    }
    Write-Host "$label is up." -ForegroundColor Green
}

# -- Ollama --------------------------------------------------------------

if (Test-Url "http://127.0.0.1:11434/api/tags") {
    Write-Host "Ollama already running."
} else {
    Write-Host "Starting Ollama..."
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Wait-ForUrl "http://127.0.0.1:11434/api/tags" "Ollama"
}

# -- Orion backend ---------------------------------------------------------
# No --model/--agent flags: orion serve falls back to config.toml's
# intelligence.default_model / agent.default_agent when omitted, so this
# always launches with whatever the user last configured (e.g. via the
# Governance screen), not a value hardcoded here that could drift out of
# sync with it.

if (Test-Url "$appUrl/health") {
    Write-Host "Orion backend already running."
} else {
    Write-Host "Starting Orion backend..."
    Start-Process -FilePath "$repoRoot\.venv\Scripts\orion.exe" -ArgumentList "serve" -WorkingDirectory $repoRoot -WindowStyle Hidden
    Wait-ForUrl "$appUrl/health" "Orion backend"
}

# -- Open the app ------------------------------------------------------------
# If the PWA is already installed, Windows/Chrome will route this to the
# installed app window instead of a browser tab.

Start-Process $appUrl
