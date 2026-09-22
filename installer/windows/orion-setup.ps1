<#
.SYNOPSIS
    Installs everything Orion needs on a Windows PC. Safe to run again: each
    step checks what is already there and only does what is missing.

.DESCRIPTION
    Run by the Orion installer right after the app is copied, and by the app
    itself to repair a broken install. No administrator rights are needed:
    everything installs for the current user, into the folder chosen in the
    installer (runtime, tools, a new Ollama and all downloaded models).

      1. Checks disk space and internet
      2. uv (Python package manager) + Python 3.12
      3. Ollama (local AI engine)            - signature-checked download
      4. Node.js LTS, portable               - only if WhatsApp was chosen
      5. Orion's Python environment + compiled Rust extension
      6. A default config for this machine
      7. A language model sized to this PC's memory, plus the memory embedder
      8. Speech-to-text and voice models, so voice works on first use

    Core features and AI models always install. Additional features are picked
    in a dialog (or with -Features) and remembered for repairs and updates.

    Nothing here is specific to one person or machine: paths come from the
    user's own profile, the model from detected hardware.

.PARAMETER PayloadDir
    Folder holding Orion's backend (pyproject.toml, uv.lock, src\, wheels\).
    The installer passes its own copy.

.PARAMETER InstallRoot
    Folder for runtime\, tools\, models\, install.json and setup.log. Defaults
    to the installed app's folder (the parent of PayloadDir).

.PARAMETER StatusFile
    Optional. Progress is also written here as JSON so the app can show it.

.PARAMETER Features
    Comma-separated additional features to install, skipping the picker:
    whatsapp, browser, documents, telegram, gpu, vision. Use "none" for none.

.PARAMETER NoPause
    Don't wait for a key press or show the picker (silent and automatic runs).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PayloadDir,
    # Where runtime\, tools\, models\ and install.json go. The installer passes
    # the folder the user chose; by default, the app folder the payload ships in.
    [string]$InstallRoot = '',
    [string]$StatusFile = '',
    [string]$Features = '',
    [switch]$NoPause
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

if (-not $InstallRoot) {
    $appDir = Split-Path -Parent $PayloadDir
    $InstallRoot = if (Test-Path (Join-Path $appDir 'Orion.exe')) { $appDir } else { Join-Path $env:LOCALAPPDATA 'Orion' }
}
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)

$RuntimeDir = Join-Path $InstallRoot 'runtime'
$ToolsDir = Join-Path $InstallRoot 'tools'
$LogFile = Join-Path $InstallRoot 'setup.log'
$PythonVersion = '3.12'
$TotalSteps = 8
$MinFreeGB = 12
# Always installed: the server, speech recognition and the voice.
$CoreExtras = @('server', 'speech', 'speech-kokoro')

# Additional features the user may choose. Each lists the Python extras it
# needs and whether it starts ticked; extra downloads are handled per step.
$OptionalFeatures = [ordered]@{
    whatsapp  = @{ Label = 'WhatsApp messaging and auto-reply'; Detail = 'Installs Node.js (about 80 MB)'; Extras = @(); Default = $true }
    browser   = @{ Label = 'Web browser automation'; Detail = 'Lets Orion open and operate web pages in Edge or Chrome'; Extras = @('browser'); Default = $true }
    documents = @{ Label = 'Read PDF documents'; Detail = 'Small (about 10 MB)'; Extras = @('pdf'); Default = $true }
    telegram  = @{ Label = 'Telegram bot'; Detail = 'Chat with Orion from Telegram'; Extras = @('channel-telegram'); Default = $false }
    gpu       = @{ Label = 'GPU power and energy monitoring'; Detail = 'NVIDIA graphics cards only'; Extras = @('gpu-metrics'); Default = $false }
    vision    = @{ Label = 'Screen and camera understanding'; Detail = 'Downloads a vision model (about 1.7 GB)'; Extras = @(); Default = $false }
}

$ModelsDir = Join-Path $InstallRoot 'models'
$HfHome = Join-Path $ModelsDir 'huggingface'
$FeaturesFile = Join-Path $InstallRoot 'features.txt'
# What this setup itself installed or downloaded, as opposed to what was
# already on the PC. The uninstaller removes only these (see Orion.iss).
$RecordFile = Join-Path $InstallRoot 'uninstall.ini'

New-Item -ItemType Directory -Force -Path $InstallRoot, $ToolsDir | Out-Null

# Keep every large download inside the chosen folder instead of the user
# profile on C: -- uv's package cache, the Python interpreter and the voice
# models. (Ollama and its models: see Install-Ollama.)
$env:UV_CACHE_DIR = Join-Path $InstallRoot 'cache\uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $ToolsDir 'python'
$env:HF_HOME = $HfHome
$Host.UI.RawUI.WindowTitle = 'Orion Setup'

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

# Writes that another process may briefly hold open (the app polls the status
# file; someone may have the log open) retry, and never fail setup: a log
# line lost is better than an install aborted.
function Write-Shared([string]$Path, [string]$Text, [switch]$Append) {
    for ($i = 0; $i -lt 10; $i++) {
        try {
            if ($Append) { [IO.File]::AppendAllText($Path, $Text, (New-Object Text.UTF8Encoding $false)) }
            else { [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding $false)) }
            return
        } catch {
            Start-Sleep -Milliseconds 100
        }
    }
}

function Write-Log([string]$Message) {
    $line = '{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Write-Shared $LogFile ($line + [Environment]::NewLine) -Append
}

function Set-Status([int]$Step, [string]$Label, [string]$Detail = '', [string]$ErrorText = '') {
    $percent = [int](($Step - 1) / $TotalSteps * 100)
    Write-Progress -Activity 'Setting up Orion' -Status "Step $Step of ${TotalSteps}: $Label" -CurrentOperation $Detail -PercentComplete $percent
    Write-Log "[$Step/$TotalSteps] $Label $Detail $ErrorText"
    if ($StatusFile) {
        $payload = @{ step = $Step; total = $TotalSteps; label = $Label; detail = $Detail; percent = $percent; error = $ErrorText; done = $false }
        Write-Shared $StatusFile ($payload | ConvertTo-Json -Compress)
    }
}

function Write-Step([int]$Step, [string]$Label) {
    Write-Host ''
    Write-Host ("[{0}/{1}] {2}" -f $Step, $TotalSteps, $Label) -ForegroundColor Yellow
    Set-Status $Step $Label
}

function Write-Ok([string]$Message) { Write-Host "      $Message" -ForegroundColor Green; Write-Log "  ok: $Message" }
function Write-Info([string]$Message) { Write-Host "      $Message" -ForegroundColor Gray; Write-Log "  $Message" }

# Runs a program, logging its output line by line (and passing each line to
# $OnLine). Windows PowerShell 5.1 turns every stderr line of a redirected
# program into an error record, which 'Stop' makes fatal -- and uv, ollama and
# Python all print ordinary progress to stderr ("Python 3.12 is already
# installed"). The exit code is the real success signal.
function Invoke-Native([string]$File, [string[]]$Arguments, [scriptblock]$OnLine = $null) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $File @Arguments 2>&1 | ForEach-Object {
            $line = "$_"
            Write-Log "    $line"
            if ($OnLine) { & $OnLine $line }
        }
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $old
    }
}

# Runs a downloaded installer and returns its exit code. Waits for the
# installer process only: Start-Process -Wait also waits for every program the
# installer launches, and Ollama's installer starts its tray app, which never
# exits -- setup hung right after the download until the window was closed.
function Invoke-Installer([string]$File, [string[]]$Arguments, [string]$What, [int]$TimeoutMinutes = 20) {
    Write-Log "  run: $File $($Arguments -join ' ')"
    $proc = Start-Process -FilePath $File -ArgumentList $Arguments -PassThru
    # Cache the handle now; without it Windows PowerShell can lose the exit code.
    $null = $proc.Handle
    if (-not $proc.WaitForExit($TimeoutMinutes * 60 * 1000)) {
        try { $proc.Kill() } catch { }
        throw "$What did not finish within $TimeoutMinutes minutes."
    }
    $proc.WaitForExit()
    Write-Log "  $What exited with code $($proc.ExitCode)"
    return $proc.ExitCode
}

function Invoke-Checked([string]$File, [string[]]$Arguments, [string]$What) {
    Write-Log "  run: $File $($Arguments -join ' ')"
    $code = Invoke-Native $File $Arguments
    if ($code -ne 0) { throw "$What failed (exit code $code). See $LogFile" }
}

function Save-Download([string]$Url, [string]$Destination, [string]$What) {
    Write-Info "Downloading $What..."
    Write-Log "  download: $Url"
    try {
        # BITS shows progress and is far faster than Invoke-WebRequest on PS 5.1.
        Start-BitsTransfer -Source $Url -Destination $Destination -DisplayName "Orion: $What" -ErrorAction Stop
    } catch {
        $old = $ProgressPreference
        $ProgressPreference = 'SilentlyContinue'
        try { Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing } finally { $ProgressPreference = $old }
    }
    if (-not (Test-Path $Destination) -or (Get-Item $Destination).Length -eq 0) { throw "Download of $What failed." }
}

function Get-Record([string]$Key) {
    if (-not (Test-Path $RecordFile)) { return '' }
    foreach ($line in Get-Content $RecordFile) {
        if ($line -match "^$([regex]::Escape($Key))=(.*)$") { return $Matches[1].Trim() }
    }
    return ''
}

# Written after every change, so a setup that stops part way still leaves an
# accurate record for the uninstaller. List values are merged, never replaced:
# a later run finds these things already present and must not forget them.
function Set-Record([string]$Key, [string]$Value, [switch]$Append) {
    $values = [ordered]@{}
    if (Test-Path $RecordFile) {
        foreach ($line in Get-Content $RecordFile) {
            if ($line -match '^([a-z_]+)=(.*)$') { $values[$Matches[1]] = $Matches[2].Trim() }
        }
    }
    if ($Append -and $values.Contains($Key) -and $values[$Key]) {
        $items = @($values[$Key].Split(',') | Where-Object { $_ })
        if ($items -notcontains $Value) { $items += $Value }
        $Value = $items -join ','
    }
    $values[$Key] = $Value
    $lines = @('[Orion]') + @($values.Keys | ForEach-Object { "$_=$($values[$_])" })
    Set-Content -Path $RecordFile -Value $lines -Encoding ASCII
}

function Find-Exe([string]$Name, [string[]]$Candidates) {
    foreach ($c in $Candidates) { if ($c -and (Test-Path $c)) { return $c } }
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Get-SavedFeatures {
    # What was chosen last time: install.json after a finished setup, or
    # features.txt when a setup stopped part way (so a retry keeps the choice).
    $infoPath = Join-Path $InstallRoot 'install.json'
    if (Test-Path $infoPath) {
        try {
            $info = Get-Content $infoPath -Raw | ConvertFrom-Json
            if ($info.PSObject.Properties.Name -contains 'features') { return @($info.features | Where-Object { $_ }) }
        } catch { }
    }
    if (Test-Path $FeaturesFile) {
        $saved = "$(Get-Content $FeaturesFile -Raw)".Trim()
        if ($saved -eq 'none') { return @() }
        return @($saved.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $OptionalFeatures.Contains($_) })
    }
    return $null
}

function Show-FeaturePicker([string[]]$Preselected) {
    Add-Type -AssemblyName System.Windows.Forms, System.Drawing
    [System.Windows.Forms.Application]::EnableVisualStyles()

    $form = New-Object System.Windows.Forms.Form
    $form.Text = 'Orion Setup - Choose features'
    $form.StartPosition = 'CenterScreen'
    $form.FormBorderStyle = 'FixedDialog'
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.TopMost = $true
    $form.ClientSize = New-Object System.Drawing.Size(520, 520)
    $form.Font = New-Object System.Drawing.Font('Segoe UI', 9.5)

    $y = 16
    $title = New-Object System.Windows.Forms.Label
    $title.Text = 'Always installed'
    $title.Font = New-Object System.Drawing.Font('Segoe UI', 10.5, [System.Drawing.FontStyle]::Bold)
    $title.Location = New-Object System.Drawing.Point(18, $y)
    $title.AutoSize = $true
    $form.Controls.Add($title)
    $y += 28

    foreach ($core in @('Orion app and assistant', 'Local AI engine (Ollama) and an AI model sized for this PC', 'Voice: speech recognition and speech', 'Memory')) {
        $cb = New-Object System.Windows.Forms.CheckBox
        $cb.Text = $core
        $cb.Checked = $true
        $cb.Enabled = $false
        $cb.Location = New-Object System.Drawing.Point(28, $y)
        $cb.Size = New-Object System.Drawing.Size(470, 22)
        $form.Controls.Add($cb)
        $y += 24
    }

    $y += 12
    $opt = New-Object System.Windows.Forms.Label
    $opt.Text = 'Additional features (add more later by running setup again)'
    $opt.Font = New-Object System.Drawing.Font('Segoe UI', 10.5, [System.Drawing.FontStyle]::Bold)
    $opt.Location = New-Object System.Drawing.Point(18, $y)
    $opt.Size = New-Object System.Drawing.Size(490, 22)
    $form.Controls.Add($opt)
    $y += 30

    $boxes = @{}
    foreach ($key in $OptionalFeatures.Keys) {
        $feature = $OptionalFeatures[$key]
        $cb = New-Object System.Windows.Forms.CheckBox
        $cb.Text = $feature.Label
        $cb.Checked = ($Preselected -contains $key)
        $cb.Location = New-Object System.Drawing.Point(28, $y)
        $cb.Size = New-Object System.Drawing.Size(470, 22)
        $form.Controls.Add($cb)
        $hint = New-Object System.Windows.Forms.Label
        $hint.Text = $feature.Detail
        $hint.ForeColor = [System.Drawing.Color]::DimGray
        $hint.Location = New-Object System.Drawing.Point(46, ($y + 21))
        $hint.Size = New-Object System.Drawing.Size(450, 18)
        $form.Controls.Add($hint)
        $boxes[$key] = $cb
        $y += 44
    }

    $ok = New-Object System.Windows.Forms.Button
    $ok.Text = 'Install'
    $ok.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $ok.Location = New-Object System.Drawing.Point(318, ($form.ClientSize.Height - 44))
    $ok.Size = New-Object System.Drawing.Size(90, 30)
    $cancel = New-Object System.Windows.Forms.Button
    $cancel.Text = 'Cancel'
    $cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $cancel.Location = New-Object System.Drawing.Point(414, ($form.ClientSize.Height - 44))
    $cancel.Size = New-Object System.Drawing.Size(90, 30)
    $form.Controls.Add($ok)
    $form.Controls.Add($cancel)
    $form.AcceptButton = $ok
    $form.CancelButton = $cancel

    if ($form.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
        throw 'Setup was cancelled. Open Orion to run setup again when you are ready.'
    }
    return @($boxes.Keys | Where-Object { $boxes[$_].Checked })
}

function Resolve-Features {
    if ($Features) {
        if ($Features -eq 'none') { return @() }
        $chosen = @($Features.Split(',') | ForEach-Object { $_.Trim().ToLower() } | Where-Object { $_ })
        $unknown = @($chosen | Where-Object { -not $OptionalFeatures.Contains($_) })
        if ($unknown.Count -gt 0) { throw "Unknown feature(s): $($unknown -join ', '). Choose from: $($OptionalFeatures.Keys -join ', ')." }
        return $chosen
    }
    $saved = Get-SavedFeatures
    $defaults = @($OptionalFeatures.Keys | Where-Object { $OptionalFeatures[$_].Default })
    if ($NoPause) {
        # Silent and automatic runs never prompt: keep what was chosen before.
        if ($null -ne $saved) { return $saved }
        return $defaults
    }
    if ($null -ne $saved) { return Show-FeaturePicker $saved }
    return Show-FeaturePicker $defaults
}

function Update-SessionPath {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

function Test-Prerequisites {
    Write-Step 1 'Checking this computer'
    if (-not (Test-Path (Join-Path $PayloadDir 'pyproject.toml'))) {
        throw "Orion's files were not found in '$PayloadDir'. Reinstall Orion."
    }
    $drive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($InstallRoot))
    $freeGB = [math]::Round($drive.AvailableFreeSpace / 1GB, 1)
    Write-Info "Installing to $InstallRoot ($freeGB GB free on $($drive.Name))"
    if ($freeGB -lt $MinFreeGB) {
        throw "Orion needs about $MinFreeGB GB of free space (the AI model alone is several GB); only $freeGB GB is free."
    }
    try {
        $null = Invoke-WebRequest -Uri 'https://ollama.com' -Method Head -UseBasicParsing -TimeoutSec 15
    } catch {
        throw 'No internet connection. Setup downloads the AI engine and model; connect and run setup again.'
    }
    Write-Ok 'Enough space and online'

    # The Orion window is drawn by Microsoft Edge WebView2 (built into Windows 11,
    # usually present on Windows 10). Install the per-user runtime if missing.
    $webviewKey = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    $hasWebView = $false
    foreach ($root in @("HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}", "HKLM:\$webviewKey", "HKCU:\$webviewKey")) {
        # StrictMode: a missing key gives $null, and reading .pv off $null throws.
        $props = Get-ItemProperty -Path $root -Name pv -ErrorAction SilentlyContinue
        $pv = if ($props) { $props.pv } else { $null }
        if ($pv -and $pv -ne '0.0.0.0') { $hasWebView = $true }
    }
    if (-not $hasWebView) {
        $bootstrapper = Join-Path $env:TEMP 'MicrosoftEdgeWebview2Setup.exe'
        Save-Download 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' $bootstrapper 'Microsoft Edge WebView2'
        $sig = Get-AuthenticodeSignature -FilePath $bootstrapper
        if ($sig.Status -ne 'Valid') { throw 'The WebView2 installer is not validly signed. Nothing was installed.' }
        Write-Info 'Installing Microsoft Edge WebView2...'
        $code = Invoke-Installer $bootstrapper @('/silent', '/install') 'The WebView2 installer'
        Remove-Item $bootstrapper -Force -ErrorAction SilentlyContinue
        if ($code -ne 0) { throw "Microsoft Edge WebView2 could not be installed (code $code)." }
        Write-Ok 'Microsoft Edge WebView2 installed'
    } else {
        Write-Ok 'Microsoft Edge WebView2 present'
    }
}

function Install-Uv {
    Write-Step 2 'Python tools (uv + Python 3.12)'
    $script:Uv = Find-Exe 'uv' @((Join-Path $env:USERPROFILE '.local\bin\uv.exe'), (Join-Path $env:USERPROFILE '.cargo\bin\uv.exe'))
    if (-not $script:Uv) {
        Write-Info 'Installing uv from astral.sh...'
        $installer = Join-Path $env:TEMP 'uv-install.ps1'
        Save-Download 'https://astral.sh/uv/install.ps1' $installer 'uv installer'
        [void](Invoke-Native 'powershell' @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $installer))
        Update-SessionPath
        $script:Uv = Find-Exe 'uv' @((Join-Path $env:USERPROFILE '.local\bin\uv.exe'))
        if (-not $script:Uv) { throw 'uv could not be installed. See the log for details.' }
        Set-Record 'installed_uv' $script:Uv
    }
    Write-Ok "uv: $script:Uv"
    # --no-bin: Orion's private Python must not drop python3.12.exe into the
    # user's own ~/.local/bin. Older uv without the flag: plain install.
    Write-Log "  run: $script:Uv python install $PythonVersion --no-bin"
    if ((Invoke-Native $script:Uv @('python', 'install', $PythonVersion, '--no-bin')) -ne 0) {
        Invoke-Checked $script:Uv @('python', 'install', $PythonVersion) "Installing Python $PythonVersion"
    }
    Write-Ok "Python $PythonVersion ready"
}

function Install-Ollama {
    Write-Step 3 'Local AI engine (Ollama)'
    $ownOllama = Join-Path $ToolsDir 'ollama'
    $candidates = @((Join-Path $ownOllama 'ollama.exe'), (Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'), (Join-Path $env:ProgramFiles 'Ollama\ollama.exe'))
    $script:Ollama = Find-Exe 'ollama' $candidates
    $userModels = [Environment]::GetEnvironmentVariable('OLLAMA_MODELS', 'User')
    if ($userModels) {
        # The user already chose where Ollama keeps models: respect it.
        $script:OllamaModels = $userModels
        $env:OLLAMA_MODELS = $userModels
    } elseif (-not $script:Ollama) {
        # A new Ollama keeps its models in the chosen install folder too. Set for
        # this user so Ollama's own tray app and CLI find them after a restart,
        # and for this process so the Ollama started below uses it right away.
        $script:OllamaModels = Join-Path $ModelsDir 'ollama'
        New-Item -ItemType Directory -Force -Path $script:OllamaModels | Out-Null
        [Environment]::SetEnvironmentVariable('OLLAMA_MODELS', $script:OllamaModels, 'User')
        $env:OLLAMA_MODELS = $script:OllamaModels
        Set-Record 'ollama_models_dir' $script:OllamaModels
    }
    if (-not $script:Ollama) {
        $ollamaNotice = 'Ollama installation may take about 5 to 10 minutes. Please do not close this window.'
        Write-Info $ollamaNotice
        Set-Status 3 'Local AI engine (Ollama)' $ollamaNotice
        $setup = Join-Path $env:TEMP 'OllamaSetup.exe'
        Save-Download 'https://ollama.com/download/OllamaSetup.exe' $setup 'Ollama (about 1 GB)'
        $sig = Get-AuthenticodeSignature -FilePath $setup
        if ($sig.Status -ne 'Valid') {
            Remove-Item $setup -Force -ErrorAction SilentlyContinue
            throw "The downloaded Ollama installer is not validly signed ($($sig.Status)). Nothing was installed."
        }
        Write-Info "Signed by: $($sig.SignerCertificate.Subject)"
        Write-Info 'Installing Ollama...'
        $code = Invoke-Installer $setup @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=`"$ownOllama`"") 'The Ollama installer'
        if ($code -ne 0) { throw "Ollama installer exited with code $code." }
        Remove-Item $setup -Force -ErrorAction SilentlyContinue
        Update-SessionPath
        $script:Ollama = Find-Exe 'ollama' $candidates
        if (-not $script:Ollama) { throw 'Ollama was installed but ollama.exe was not found.' }
        Set-Record 'installed_ollama' $ownOllama
        Restart-OllamaTray $ownOllama
    }
    Write-Ok "Ollama: $script:Ollama"

    if (-not (Test-OllamaUp)) {
        Write-Info 'Starting Ollama...'
        Start-Process -FilePath $script:Ollama -ArgumentList 'serve' -WindowStyle Hidden | Out-Null
        $deadline = (Get-Date).AddSeconds(60)
        while (-not (Test-OllamaUp) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 2 }
        if (-not (Test-OllamaUp)) { throw 'Ollama did not start within 60 seconds.' }
    }
    Write-Ok 'Ollama is running'
}

# Ollama's installer starts its tray app itself. Restart it from here so it
# runs with OLLAMA_MODELS pointing at the install folder: otherwise the tray
# app looked for models in the default location until the user signed out
# and back in.
function Restart-OllamaTray([string]$OllamaDir) {
    $tray = Join-Path $OllamaDir 'ollama app.exe'
    if (-not (Test-Path $tray)) { return }
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path.StartsWith($OllamaDir, [StringComparison]::OrdinalIgnoreCase) } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    Start-Process -FilePath $tray | Out-Null
    $deadline = (Get-Date).AddSeconds(60)
    while (-not (Test-OllamaUp) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 2 }
    Write-Log "  Ollama tray app restarted with OLLAMA_MODELS=$env:OLLAMA_MODELS"
}

function Get-OllamaModels {
    try {
        return @((Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 10).models | ForEach-Object { $_.name })
    } catch { return @() }
}

function Test-OllamaUp {
    try { $null = Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/tags' -UseBasicParsing -TimeoutSec 3; return $true } catch { return $false }
}

function Install-Node {
    Write-Step 4 'Node.js (used by WhatsApp)'
    if ($script:Chosen -notcontains 'whatsapp') { Write-Ok 'Skipped (WhatsApp not selected)'; return }
    $portable = Join-Path $ToolsDir 'node\node.exe'
    $existing = Find-Exe 'node' @($portable)
    if ($existing) {
        $major = 0
        try { $major = [int](((& $existing --version) -replace '^v', '').Split('.')[0]) } catch { }
        if ($major -ge 22) { Write-Ok "Node.js v$major found: $existing"; return }
        Write-Info "Node.js v$major is too old (22+ needed); installing a private copy."
    }

    $index = Invoke-RestMethod -Uri 'https://nodejs.org/dist/index.json' -UseBasicParsing
    $release = $index | Where-Object { $_.lts -and $_.version -like 'v22.*' } | Select-Object -First 1
    if (-not $release) { throw 'Could not find the current Node.js 22 LTS release.' }
    $version = $release.version
    $zipName = "node-$version-win-x64.zip"
    $base = "https://nodejs.org/dist/$version"
    $zip = Join-Path $env:TEMP $zipName
    Save-Download "$base/$zipName" $zip "Node.js $version"

    $sums = (Invoke-WebRequest -Uri "$base/SHASUMS256.txt" -UseBasicParsing).Content
    $expected = ($sums -split "`n" | Where-Object { $_ -match [regex]::Escape($zipName) } | Select-Object -First 1) -split '\s+' | Select-Object -First 1
    $actual = (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLower()
    if (-not $expected -or $actual -ne $expected.ToLower()) {
        Remove-Item $zip -Force -ErrorAction SilentlyContinue
        throw 'The Node.js download failed its checksum. Nothing was installed.'
    }

    Set-Record 'installed_node' (Join-Path $ToolsDir 'node')
    $target = Join-Path $ToolsDir 'node'
    $extract = Join-Path $ToolsDir 'node-extract'
    Remove-Item $extract -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive -Path $zip -DestinationPath $extract -Force
    Remove-Item $target -Recurse -Force -ErrorAction SilentlyContinue
    Move-Item -Path (Join-Path $extract "node-$version-win-x64") -Destination $target
    Remove-Item $extract, $zip -Recurse -Force -ErrorAction SilentlyContinue
    Write-Ok "Node.js $version installed to $target"
}

function Install-OrionRuntime {
    Write-Step 5 "Orion's Python environment"
    New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
    # Mirror the shipped backend, but keep the environment that is already built.
    $robo = Start-Process -FilePath robocopy -ArgumentList @(
        "`"$PayloadDir`"", "`"$RuntimeDir`"", '/MIR', '/XD', '.venv', '/NFL', '/NDL', '/NJH', '/NJS', '/NP'
    ) -Wait -PassThru -WindowStyle Hidden
    if ($robo.ExitCode -ge 8) { throw "Copying Orion's files failed (robocopy code $($robo.ExitCode))." }

    Push-Location $RuntimeDir
    try {
        # only-managed: the environment must not depend on a Python the user
        # installed themselves and may later remove.
        $syncArgs = @('sync', '--frozen', '--no-dev', '--python', $PythonVersion, '--python-preference', 'only-managed')
        $extras = @($CoreExtras)
        foreach ($key in $script:Chosen) { $extras += $OptionalFeatures[$key].Extras }
        foreach ($extra in ($extras | Select-Object -Unique)) { $syncArgs += @('--extra', $extra) }
        Write-Info 'Installing Python packages (first time takes a few minutes)...'
        Invoke-Checked $script:Uv $syncArgs 'Installing Python packages'

        $wheel = Get-ChildItem -Path (Join-Path $RuntimeDir 'wheels') -Filter 'orion_rust-*.whl' -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $wheel) { throw 'The compiled Orion extension (orion_rust wheel) is missing from this installer.' }
        $python = Join-Path $RuntimeDir '.venv\Scripts\python.exe'
        Invoke-Checked $script:Uv @('pip', 'install', '--python', $python, '--no-deps', '--reinstall', $wheel.FullName) 'Installing the Orion extension'

        # No quotes inside the code: Windows PowerShell 5.1 strips them from native arguments.
        Invoke-Checked $python @('-c', 'import orion, orion_rust') 'Checking the Orion install'
    } finally {
        Pop-Location
    }
    Write-Ok 'Python environment ready'
}

function Initialize-Config {
    Write-Step 6 'Default settings'
    $configPath = Join-Path $env:USERPROFILE '.orion\config.toml'
    if (Test-Path $configPath) {
        Write-Ok 'Existing settings kept'
        return
    }
    $orion = Join-Path $RuntimeDir '.venv\Scripts\orion.exe'
    Invoke-Checked $orion @('init', '--engine', 'ollama', '--no-download', '--no-scan') 'Creating default settings'
    $script:CreatedConfig = $configPath
    Write-Ok "Settings created at $configPath"
}

function Set-ConfigModel([string]$Model) {
    # Only settings this setup just created: an existing user's choice is kept.
    if (-not $script:CreatedConfig -or -not (Test-Path $script:CreatedConfig)) { return }
    $text = [IO.File]::ReadAllText($script:CreatedConfig)
    $updated = [regex]::Replace($text, '(?m)^(\s*default_model\s*=\s*)"[^"]*"', "`${1}`"$Model`"")
    if ($updated -ne $text) {
        [IO.File]::WriteAllText($script:CreatedConfig, $updated, (New-Object Text.UTF8Encoding $false))
        Write-Log "default_model set to $Model"
    }
}

function Select-Model {
    # Same tiers as the desktop launcher (lib.rs QWEN35_MODELS): the largest
    # model of the everyday sizes that this machine's memory can hold.
    $ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
    if ($ramGB -ge 8) { return @{ Model = 'qwen3.5:4b'; RamGB = $ramGB; SizeGB = 3.4 } }
    if ($ramGB -ge 6) { return @{ Model = 'qwen3.5:2b'; RamGB = $ramGB; SizeGB = 2.7 } }
    if ($ramGB -ge 4) { return @{ Model = 'qwen3.5:0.8b'; RamGB = $ramGB; SizeGB = 1.0 } }
    return @{ Model = 'qwen3:0.6b'; RamGB = $ramGB; SizeGB = 0.5 }
}

function Install-Models {
    Write-Step 7 'AI model'
    $choice = Select-Model
    $script:Model = $choice.Model
    Write-Info ("This PC has {0} GB of memory: using {1} (about {2} GB download)." -f $choice.RamGB, $choice.Model, $choice.SizeGB)
    $models = @($choice.Model, 'nomic-embed-text')
    if ($script:Chosen -contains 'vision') { $models += 'moondream' }
    $present = Get-OllamaModels
    foreach ($m in $models) {
        Set-Status 7 'AI model' "Downloading $m"
        $alreadyHere = ($present -contains $m) -or ($present -contains "$($m):latest")
        Write-Info "ollama pull $m"
        # Not redirected, so the download progress bar stays visible; 'Continue'
        # because ollama draws that bar on stderr (see Invoke-Native).
        $old = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try { & $script:Ollama pull $m } finally { $ErrorActionPreference = $old }
        if ($LASTEXITCODE -ne 0) { throw "Downloading the model '$m' failed. Check the connection and run setup again." }
        if (-not $alreadyHere) { Set-Record 'pulled_models' $m -Append }
    }
    Set-ConfigModel $choice.Model
    Write-Ok "Models ready: $($models -join ', ')"
}

function Initialize-Voice {
    Write-Step 8 'Voice (speech recognition and speech)'
    Set-Status 8 'Voice (speech recognition and speech)' 'Downloading voice models (about 500 MB)'
    $python = Join-Path $RuntimeDir '.venv\Scripts\python.exe'
    # Prints each stage as it starts, so a slow download never looks frozen,
    # and records results in setup.log itself (its output is not captured).
    $warm = @'
import os, sys, time, traceback, warnings
warnings.filterwarnings("ignore")
LOG = os.environ.get("ORION_SETUP_LOG", "")

def say(message):
    print("      " + message, flush=True)
    if LOG:
        try:
            with open(LOG, "a", encoding="utf-8") as log:
                log.write(time.strftime("%Y-%m-%d %H:%M:%S") + "    voice: " + message + "\n")
        except OSError:
            pass

ok = True
try:
    say("Loading speech tools...")
    from orion.core.config import load_config
    from orion.speech._discovery import whisper_model_for
    from orion.speech._model_files import prepare_whisper
    from orion.speech.faster_whisper import FasterWhisperBackend
    speech = load_config().speech
    # The model Orion will actually load (base.en when speech is English).
    name = whisper_model_for(speech.model, speech.language)
    say("Downloading speech recognition (Whisper " + name + ", about 150 MB)...")
    prepare_whisper(name, say)
    stt = FasterWhisperBackend(model_size=name, device="cpu", compute_type="int8")
    stt._ensure_model()
    say("Speech recognition ready")
except Exception as exc:
    ok = False
    say("Speech recognition not prepared: " + str(exc))
    say(traceback.format_exc())
try:
    say("Loading the voice engine (this can take a minute)...")
    from orion.speech._model_files import prepare_kokoro
    from orion.speech.kokoro_tts import KokoroTTSBackend
    say("Downloading Orion's voice (Kokoro, about 330 MB)...")
    prepare_kokoro(say)
    result = KokoroTTSBackend(device="cpu").synthesize("Ready.", voice_id="af_heart")
    if not result.audio or result.duration_seconds <= 0:
        raise RuntimeError("The voice engine produced no audio")
    say("Voice ready")
except Exception as exc:
    ok = False
    say("Voice not prepared: " + str(exc))
    say(traceback.format_exc())
sys.exit(0 if ok else 3)
'@
    $warmFile = Join-Path $env:TEMP 'orion-warm-voice.py'
    Set-Content -Path $warmFile -Value $warm -Encoding UTF8
    $env:ORION_SETUP_LOG = $LogFile
    $env:PYTHONIOENCODING = 'utf-8'
    $env:HF_HUB_DISABLE_SYMLINKS_WARNING = '1'
    $env:HF_HUB_VERBOSITY = 'error'
    # Give up on a stalled connection instead of waiting forever.
    $env:HF_HUB_DOWNLOAD_TIMEOUT = '60'
    $env:HF_HUB_ETAG_TIMEOUT = '30'
    Write-Log "  run: $python -u $warmFile"
    # Same console, so Hugging Face's download progress bars stay visible.
    $proc = Start-Process -FilePath $python -ArgumentList @('-u', '-W', 'ignore', "`"$warmFile`"") -NoNewWindow -PassThru
    $null = $proc.Handle
    $minutes = 30
    if (-not $proc.WaitForExit($minutes * 60 * 1000)) {
        try { $proc.Kill() } catch { }
        Write-Info "Voice download stopped after $minutes minutes."
        $code = -1
    } else {
        $proc.WaitForExit()
        $code = $proc.ExitCode
    }
    Remove-Item $warmFile -Force -ErrorAction SilentlyContinue
    Write-Log "  voice warm-up exit code $code"
    if ($code -ne 0) {
        throw "Voice models could not be prepared (exit code $code). See $LogFile and run setup again."
    }
    Write-Ok 'Voice models ready'
}

function Save-InstallInfo {
    $info = @{
        runtime     = $RuntimeDir
        python      = (Join-Path $RuntimeDir '.venv\Scripts\python.exe')
        orion       = (Join-Path $RuntimeDir '.venv\Scripts\orion.exe')
        node_dir    = (Join-Path $ToolsDir 'node')
        ollama      = $script:Ollama
        ollama_models = $script:OllamaModels
        hf_home     = $HfHome
        model       = $script:Model
        features    = @($script:Chosen)
        installedAt = (Get-Date).ToString('o')
    }
    $info | ConvertTo-Json | Set-Content -Path (Join-Path $InstallRoot 'install.json') -Encoding UTF8
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

$script:Uv = $null
$script:Ollama = $null
$script:Model = $null
$script:OllamaModels = ''
$script:CreatedConfig = $null
$script:Chosen = @()

Write-Host ''
Write-Host '  ORION  -  setting up your on-device AI' -ForegroundColor White
Write-Host "  Everything installs for this Windows user only. Log: $LogFile" -ForegroundColor DarkGray
Write-Log '===== Orion setup started ====='

$exitCode = 0
try {
    $script:Chosen = @(Resolve-Features)
    Write-Log "Features: core + $($script:Chosen -join ', ')"
    Set-Content -Path $FeaturesFile -Value $(if ($script:Chosen.Count) { $script:Chosen -join ',' } else { 'none' }) -Encoding ASCII
    Test-Prerequisites
    Install-Uv
    Install-Ollama
    Install-Node
    Install-OrionRuntime
    Initialize-Config
    Install-Models
    Initialize-Voice
    Save-InstallInfo
    Write-Progress -Activity 'Setting up Orion' -Completed
    if ($StatusFile) { Write-Shared $StatusFile (@{ step = $TotalSteps; total = $TotalSteps; label = 'Done'; percent = 100; done = $true; error = '' } | ConvertTo-Json -Compress) }
    Write-Host ''
    Write-Host '  Orion is ready. Open it from the Start menu.' -ForegroundColor Green
    Write-Log '===== Orion setup finished ====='
} catch {
    $exitCode = 1
    $message = $_.Exception.Message
    Write-Log "FAILED: $message"
    if ($StatusFile) { Write-Shared $StatusFile (@{ step = 0; total = $TotalSteps; label = 'Setup failed'; percent = 0; done = $false; error = $message } | ConvertTo-Json -Compress) }
    Write-Host ''
    Write-Host "  Setup could not finish: $message" -ForegroundColor Red
    Write-Host "  Fix the problem above, then open Orion again: it resumes where setup stopped." -ForegroundColor Red
    Write-Host "  Details: $LogFile" -ForegroundColor DarkGray
}

if (-not $NoPause) {
    Write-Host ''
    Write-Host '  Press any key to close this window.' -ForegroundColor DarkGray
    try { $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown') } catch { }
}
exit $exitCode
