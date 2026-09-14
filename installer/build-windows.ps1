<#
.SYNOPSIS
    Builds OrionSetup-<version>.exe.

.DESCRIPTION
      1. Refreshes uv.lock so the installer's dependency set matches pyproject.toml
      2. Compiles the orion_rust extension into a wheel for Python 3.12
      3. Stages Orion's backend (source only - no caches, node_modules or
         generated tools) and checks it for personal data and secrets
      4. Builds the desktop app (Tauri, release, no bundle)
      5. Compiles installer\windows\Orion.iss with Inno Setup

      6. With TAURI_SIGNING_PRIVATE_KEY set (and TAURI_SIGNING_PRIVATE_KEY_PASSWORD
         if the key has one): signs the installer and writes
         orion-windows-update.json, which installed copies of Orion read to
         offer the update

    Output: installer\dist\OrionSetup-<version>.exe
            installer\dist\OrionSetup-<version>.exe.sig      (when signed)
            installer\dist\orion-windows-update.json         (when signed)

    To ship an update, create a GitHub release tagged v<version> on the release
    repository and upload those three files. Installed apps only install an
    update whose signature matches the public key in tauri.conf.json.

    Nothing is taken from the machine running the build other than the
    repository itself: no user settings, keys, models or credentials. The
    signing key is read from the environment and never written anywhere.
#>
[CmdletBinding()]
param(
    [string]$Version = '',
    [string]$IsccPath = '',
    [string]$ReleaseRepo = 'AstraDev-Labs/Orion-AI',
    [string]$ReleaseNotes = '',
    [switch]$SkipApp,
    [switch]$SkipWheel
)

$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
$Stage = Join-Path $PSScriptRoot 'stage\backend'
$Dist = Join-Path $PSScriptRoot 'dist'

function Step([string]$Text) { Write-Host ''; Write-Host "==> $Text" -ForegroundColor Cyan }
function Run([string]$File, [string[]]$Arguments) {
    Write-Host "    $File $($Arguments -join ' ')" -ForegroundColor DarkGray
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$File failed with exit code $LASTEXITCODE" }
}

# --- Tools -------------------------------------------------------------------
if (-not $Version) {
    $Version = (Get-Content (Join-Path $Repo 'frontend\src-tauri\tauri.conf.json') -Raw | ConvertFrom-Json).version
}
if (-not $IsccPath) {
    $IsccPath = @(
        (Join-Path $env:ProgramFiles 'Inno Setup 7\ISCC.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 7\ISCC.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if (-not $IsccPath) {
        $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if ($cmd) { $IsccPath = $cmd.Source }
    }
}
if (-not $IsccPath) { throw 'Inno Setup (ISCC.exe) was not found. Install Inno Setup or pass -IsccPath.' }
foreach ($tool in @('uv', 'cargo', 'npm')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "'$tool' is required to build the installer." }
}
Write-Host "Building Orion $Version installer" -ForegroundColor White

Push-Location $Repo
try {
    # --- 1. Lock ---------------------------------------------------------------
    Step 'Refreshing uv.lock'
    Run 'uv' @('lock')

    # --- 2. Rust extension wheel ---------------------------------------------
    $wheelDir = Join-Path $Stage 'wheels'
    if (-not $SkipWheel) {
        Step 'Building orion_rust wheel (Python 3.12)'
        Run 'uv' @('python', 'install', '3.12')
        $py312 = (& uv python find 3.12).Trim()
        $wheelOut = Join-Path $PSScriptRoot 'stage\wheels-build'
        Remove-Item $wheelOut -Recurse -Force -ErrorAction SilentlyContinue
        Run 'uv' @('run', '--no-sync', 'maturin', 'build', '--release', '-m', 'rust/crates/orion-python/Cargo.toml', '--interpreter', $py312, '-o', $wheelOut)
    }

    # --- 3. Stage backend ------------------------------------------------------
    Step 'Staging backend'
    $keepWheels = Join-Path $PSScriptRoot 'stage\wheels-build'
    Remove-Item $Stage -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $Stage, $wheelDir | Out-Null
    foreach ($file in @('pyproject.toml', 'uv.lock', 'README.md', 'LICENSE')) {
        if (Test-Path $file) { Copy-Item $file $Stage }
    }
    # Everything the Python package build needs (see [tool.hatch] in pyproject.toml).
    $excludeDirs = @('__pycache__', 'node_modules', '.pytest_cache', '.mypy_cache', '.ruff_cache')
    foreach ($dir in @('src', 'scripts\install')) {
        $roboArgs = @($dir, (Join-Path $Stage $dir), '/E', '/XD') + $excludeDirs + @('/XF', '*.pyc', '*.pyo', '*.png.bak', '/NFL', '/NDL', '/NJH', '/NJS', '/NP')
        & robocopy @roboArgs | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "Copying $dir failed (robocopy $LASTEXITCODE)" }
    }
    # Tools the developer's own Orion generated at runtime are personal, not product.
    Get-ChildItem (Join-Path $Stage 'src\orion\tools\generated') -Filter '*.py' -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne '__init__.py' } | Remove-Item -Force
    # Stray files that are not source.
    Get-ChildItem $Stage -Recurse -Include '*.log', '*.db', '*.sqlite', '*.png' -File -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch '\\(static|assets)\\' } | Remove-Item -Force
    $wheel = Get-ChildItem $keepWheels -Filter 'orion_rust-*.whl' -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $wheel) { throw 'No orion_rust wheel found. Run without -SkipWheel.' }
    Copy-Item $wheel.FullName $wheelDir
    Write-Host "    wheel: $($wheel.Name)"

    # --- Privacy check: nothing personal or secret may ship --------------------
    Step 'Checking the staged files for personal data and secrets'
    $patterns = @(
        'sk-[A-Za-z0-9_-]{20,}', 'ghp_[A-Za-z0-9]{36}', 'github_pat_[A-Za-z0-9_]{40,}', 'xox[bap]-[0-9A-Za-z-]{10,}',
        'AKIA[0-9A-Z]{16}', '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----', '\b\d{8,10}:AA[0-9A-Za-z_-]{30,}\b'
    )
    # The build machine's own account name must not appear in shipped paths.
    $userPath = [regex]::Escape("\Users\$env:USERNAME\")
    $userPathFwd = [regex]::Escape("/Users/$env:USERNAME/")
    $patterns += @($userPath, $userPathFwd)
    $files = Get-ChildItem $Stage -Recurse -File -Include '*.py', '*.toml', '*.json', '*.md', '*.ts', '*.js', '*.txt', '*.yaml', '*.yml', '*.ps1', '*.sh'
    # Scanner test data deliberately contains fake keys; it is still checked
    # for the build machine's personal paths.
    $sampleData = { $_.FullName -match '\\evals\\datasets\\' }
    $hits = @(
        $files | Where-Object { -not (& $sampleData) } | Select-String -Pattern $patterns -ErrorAction SilentlyContinue
        $files | Where-Object $sampleData | Select-String -Pattern @($userPath, $userPathFwd) -ErrorAction SilentlyContinue
    )
    if ($hits) {
        $hits | Select-Object -First 20 | ForEach-Object { Write-Host "    $($_.Path):$($_.LineNumber): $($_.Line.Trim())" -ForegroundColor Red }
        throw 'Personal data or a secret was found in the files to ship. Remove it and build again.'
    }
    Write-Host '    clean' -ForegroundColor Green

    # --- 4. Desktop app ----------------------------------------------------------
    $appExe = Join-Path $Repo 'frontend\src-tauri\target\release\orion-desktop.exe'
    if (-not $SkipApp) {
        Step 'Building the desktop app (release)'
        Push-Location (Join-Path $Repo 'frontend')
        try {
            Run 'npm' @('install', '--no-audit', '--no-fund')
            # Inno Setup is the installer, so skip Tauri's own bundles and updater artifacts.
            Run 'npm' @('run', 'tauri', '--', 'build', '--no-bundle', '--config', (Join-Path $PSScriptRoot 'windows\tauri.inno.conf.json'))
        } finally {
            Pop-Location
        }
    }
    if (-not (Test-Path $appExe)) { throw "App executable not found at $appExe" }

    # --- 5. Installer ------------------------------------------------------------
    Step 'Compiling the installer with Inno Setup'
    New-Item -ItemType Directory -Force -Path $Dist | Out-Null
    Run $IsccPath @("/DAppVersion=$Version", "/DAppExe=$appExe", (Join-Path $PSScriptRoot 'windows\Orion.iss'))

    $out = Join-Path $Dist "OrionSetup-$Version.exe"
    $sizeMB = [math]::Round((Get-Item $out).Length / 1MB, 1)

    # --- 6. In-app update package ----------------------------------------------
    $manifestPath = Join-Path $Dist 'orion-windows-update.json'
    Remove-Item "$out.sig", $manifestPath -Force -ErrorAction SilentlyContinue
    if ($env:TAURI_SIGNING_PRIVATE_KEY) {
        Step 'Signing the installer for in-app updates'
        Push-Location (Join-Path $Repo 'frontend')
        try {
            $signArgs = @('run', 'tauri', '--', 'signer', 'sign')
            if (-not $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD) { $signArgs += @('--password', '""') }
            Run 'npm' ($signArgs + @($out))
        } finally {
            Pop-Location
        }
        if (-not (Test-Path "$out.sig")) { throw 'Signing did not produce a .sig file.' }
        $manifest = [ordered]@{
            version   = $Version
            notes     = $ReleaseNotes
            pub_date  = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
            url       = "https://github.com/$ReleaseRepo/releases/download/v$Version/OrionSetup-$Version.exe"
            signature = (Get-Content "$out.sig" -Raw).Trim()
        }
        # No byte-order mark: the app's JSON reader expects plain UTF-8.
        [IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
        Write-Host "    signed; update file: $manifestPath" -ForegroundColor Green
        Write-Host "    Publish: GitHub release v$Version on $ReleaseRepo with OrionSetup-$Version.exe, its .sig and orion-windows-update.json" -ForegroundColor Gray
    } else {
        Write-Warning 'TAURI_SIGNING_PRIVATE_KEY is not set, so no in-app update package was made. Installed copies only accept signed updates.'
    }

    Write-Host ''
    Write-Host "Installer ready: $out ($sizeMB MB)" -ForegroundColor Green
} finally {
    Pop-Location
}
