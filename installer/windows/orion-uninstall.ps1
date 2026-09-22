<#
.SYNOPSIS
    Removes what Orion setup installed, for the parts the user chose.

.DESCRIPTION
    Run by Orion's uninstaller (Orion.iss) before it deletes the app's own files.
    Only removes what setup itself installed or downloaded, as recorded in
    <AppDir>\uninstall.ini by orion-setup.ps1: an Ollama, uv or AI model that was
    already on this PC before Orion is never touched.

.PARAMETER AppDir
    The folder Orion was installed to.

.PARAMETER Remove
    Comma-separated parts to remove:
      runtime  Orion's Python environment, its tools and download cache
      models   AI models Orion downloaded
      voice    speech recognition and voice models
      engine   Ollama, if Orion setup installed it
      node     Node.js, if setup installed a private copy (used by WhatsApp)
      uv       uv, if setup installed it
      data     settings, memories, conversations and linked accounts (~\.orion)
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$AppDir,
    [string]$Remove = 'runtime,models,voice,engine,node,uv'
)

$ErrorActionPreference = 'Continue'
$AppDir = [IO.Path]::GetFullPath($AppDir).TrimEnd('\')
$LogFile = Join-Path $env:TEMP 'orion-uninstall.log'
$RecordFile = Join-Path $AppDir 'uninstall.ini'
$InstallInfoFile = Join-Path $AppDir 'install.json'
$Parts = @($Remove.Split(',') | ForEach-Object { $_.Trim().ToLower() } | Where-Object { $_ })

function Write-Log([string]$Message) {
    $line = '{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    try { Add-Content -Path $LogFile -Value $line -Encoding UTF8 } catch { }  # logging never stops the uninstall
}

function Get-Record([string]$Key) {
    if (-not (Test-Path $RecordFile)) { return '' }
    foreach ($line in Get-Content $RecordFile) {
        if ($line -match "^$([regex]::Escape($Key))=(.*)$") { return $Matches[1].Trim() }
    }
    return ''
}

function Get-InstallInfoValue([string]$Key) {
    if (-not (Test-Path -LiteralPath $InstallInfoFile)) { return '' }
    try {
        $info = Get-Content -LiteralPath $InstallInfoFile -Raw | ConvertFrom-Json
        $property = $info.PSObject.Properties[$Key]
        if ($property -and $null -ne $property.Value) {
            if (($property.Value -is [System.Collections.IEnumerable]) -and -not ($property.Value -is [string])) {
                return (@($property.Value) -join ',').Trim()
            }
            return "$($property.Value)".Trim()
        }
    } catch {
        Write-Log "  could not read install.json: $($_.Exception.Message)"
    }
    return ''
}

function Add-Unique([string[]]$Values, [string]$Value) {
    if (-not $Value) { return @($Values) }
    if ($Values -contains $Value) { return @($Values) }
    return @($Values + $Value)
}

# Releases before 1.0.2A did not write uninstall.ini. They installed the
# selected language model plus Orion's fixed memory and vision helpers in the
# user's default Ollama library. Recover those names from install.json or the
# Orion configuration so an old install can still clean up after itself.
function Get-LegacyOrionModels {
    $models = @()
    $configured = Get-InstallInfoValue 'model'
    if (-not $configured) {
        $config = Join-Path $env:USERPROFILE '.orion\config.toml'
        if (Test-Path -LiteralPath $config) {
            try {
                $text = Get-Content -LiteralPath $config -Raw
                if ($text -match '(?m)^\s*default_model\s*=\s*"([^"]+)"') { $configured = $Matches[1].Trim() }
            } catch { }
        }
    }
    # Orion's setup selects a Qwen model from the machine's memory tier. Do not
    # infer arbitrary configured models, which may belong to another app.
    if ($configured -match '^qwen3(?:\.5)?:[0-9]+(?:\.[0-9]+)?b$') { $models = Add-Unique $models $configured }
    # Orion's memory system always downloads this alongside the selected chat model.
    $models = Add-Unique $models 'nomic-embed-text'

    $features = Get-InstallInfoValue 'features'
    if ($features -match '(^|,)vision(,|$)') { $models = Add-Unique $models 'moondream' }

    # Legacy feature selections were not always persisted. If the model is
    # present under this exact Orion-only optional feature name, include it.
    try {
        $listed = @((Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5).models | ForEach-Object { $_.name })
        if (($listed -contains 'moondream') -or ($listed -contains 'moondream:latest')) { $models = Add-Unique $models 'moondream' }
    } catch { }
    return @($models)
}

function Test-Inside([string]$Path, [string]$Parent) {
    if (-not $Path) { return $false }
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\') + '\'
    return $full.StartsWith($Parent.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)
}

# rd handles the long paths inside Python environments that Remove-Item on
# Windows PowerShell 5.1 fails on.
function Remove-Tree([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    # Windows can report a process as stopped while it still closes file
    # handles. Retry the native long-path removal and stop any remaining child
    # process between attempts; this prevents an empty runtime directory from
    # keeping the whole Orion install registered after uninstall.
    for ($attempt = 1; $attempt -le 6; $attempt++) {
        & cmd.exe /d /c "rd /s /q `"\\?\$Path`"" 2>&1 | ForEach-Object { Write-Log "    $_" }
        if (-not (Test-Path -LiteralPath $Path)) {
            Write-Log "  removed $Path"
            return
        }
        Stop-ProcessesUnder $Path
        if ($attempt -lt 6) { Start-Sleep -Seconds 1 }
    }
    Write-Log "  could not fully remove $Path after retries"
}

function Stop-ProcessesUnder([string]$Folder) {
    if (-not (Test-Path -LiteralPath $Folder)) { return }
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        (Test-Inside $_.ExecutablePath $Folder) -or ($_.CommandLine -and $_.CommandLine.IndexOf($Folder, [StringComparison]::OrdinalIgnoreCase) -ge 0)
    } | Where-Object { $_.ProcessId -ne $PID } | ForEach-Object {
        Write-Log "  stopping $($_.Name) ($($_.ProcessId))"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

# Ollama may have been installed before Orion, while Orion configured it to use
# a private model folder below AppDir.  In that case its background server holds
# blobs open, so rd cannot remove the model folder.  Only stop Ollama when the
# user's current OLLAMA_MODELS setting points at this Orion-owned folder; a
# separate Ollama installation using its own models is left running.
function Stop-OllamaServingModels([string]$ModelsDir) {
    if (-not $ModelsDir -or -not (Test-Inside $ModelsDir $AppDir)) { return }
    $configured = [Environment]::GetEnvironmentVariable('OLLAMA_MODELS', 'User')
    if (-not $configured) { return }
    try {
        $sameFolder = [IO.Path]::GetFullPath($configured).TrimEnd('\') -ieq [IO.Path]::GetFullPath($ModelsDir).TrimEnd('\')
    } catch {
        $sameFolder = $false
    }
    if (-not $sameFolder) { return }

    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessId -ne $PID -and $_.Name -like 'ollama*.exe'
    } | ForEach-Object {
        Write-Log "  stopping Ollama process $($_.Name) ($($_.ProcessId)) serving Orion models"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
}

function Test-OllamaUp {
    try { $null = Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/tags' -UseBasicParsing -TimeoutSec 3; return $true } catch { return $false }
}

function Remove-LegacyVoiceCaches {
    # Old releases used Hugging Face's default cache. These repository names
    # are the voice packages Orion installs, so remove only their directories
    # and matching lock files, never the user's whole Hugging Face cache.
    $hub = Join-Path $env:USERPROFILE '.cache\huggingface\hub'
    if (-not (Test-Path -LiteralPath $hub)) { return }
    $voiceDirs = @(
        Get-ChildItem -LiteralPath $hub -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -eq 'models--hexgrad--Kokoro-82M' -or $_.Name -like 'models--Systran--faster-whisper-*' }
    )
    foreach ($dir in $voiceDirs) {
        Remove-Tree $dir.FullName
        Remove-Tree (Join-Path $hub ('.locks\' + $dir.Name))
    }
}

Write-Log "===== Orion uninstall: $AppDir; removing: $($Parts -join ', ') ====="

# Orion itself first: the app, its server and the WhatsApp bridge hold files open.
$ownOllama = Get-Record 'installed_ollama'
foreach ($folder in @((Join-Path $AppDir 'runtime'), (Join-Path $AppDir 'tools\python'), (Join-Path $AppDir 'tools\node'))) {
    Stop-ProcessesUnder $folder
}
Get-Process -Name 'Orion' -ErrorAction SilentlyContinue | Where-Object { Test-Inside $_.Path $AppDir } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# --- AI models --------------------------------------------------------------
if ($Parts -contains 'models') {
    $modelsDir = Get-Record 'ollama_models_dir'
    if (-not $modelsDir) { $modelsDir = Get-InstallInfoValue 'ollama_models' }
    # Installers before uninstall.ini was introduced still stored their Ollama
    # models below the app folder.  This location is unambiguously Orion-owned,
    # so it is safe to use as a fallback without touching a user's normal
    # ~/.ollama model library.
    if (-not $modelsDir) {
        $legacyModelsDir = Join-Path $AppDir 'models\ollama'
        if (Test-Path -LiteralPath $legacyModelsDir) { $modelsDir = $legacyModelsDir }
    }
    if ($modelsDir -and (Test-Inside $modelsDir $AppDir)) {
        # A model folder setup created inside the install folder: stop the
        # Ollama serving it, delete the folder, and stop pointing Ollama at it.
        if ($ownOllama) { Stop-ProcessesUnder $ownOllama }
        Stop-OllamaServingModels $modelsDir
        Remove-Tree $modelsDir
        $current = [Environment]::GetEnvironmentVariable('OLLAMA_MODELS', 'User')
        if ($current -and ([IO.Path]::GetFullPath($current).TrimEnd('\') -ieq [IO.Path]::GetFullPath($modelsDir).TrimEnd('\'))) {
            [Environment]::SetEnvironmentVariable('OLLAMA_MODELS', $null, 'User')
            Write-Log '  cleared OLLAMA_MODELS'
        }
    }
    $pulled = @((Get-Record 'pulled_models').Split(',') | Where-Object { $_ })
    if ($pulled.Count -eq 0 -and -not ($modelsDir -and (Test-Inside $modelsDir $AppDir))) {
        $pulled = @(Get-LegacyOrionModels)
        if ($pulled.Count -gt 0) { Write-Log "  recovered legacy Orion models: $($pulled -join ', ')" }
    }
    if ($pulled.Count -gt 0 -and -not ($modelsDir -and (Test-Inside $modelsDir $AppDir))) {
        # Models Orion downloaded into an Ollama that was already here: delete
        # just those, through Ollama itself.
        $started = $null
        if (-not (Test-OllamaUp)) {
            $exe = @((Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'), (Join-Path $env:ProgramFiles 'Ollama\ollama.exe')) | Where-Object { Test-Path $_ } | Select-Object -First 1
            if (-not $exe) { $cmd = Get-Command ollama -ErrorAction SilentlyContinue; if ($cmd) { $exe = $cmd.Source } }
            if ($exe) {
                $started = Start-Process -FilePath $exe -ArgumentList 'serve' -WindowStyle Hidden -PassThru
                $deadline = (Get-Date).AddSeconds(30)
                while (-not (Test-OllamaUp) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 1 }
            }
        }
        foreach ($m in $pulled) {
            try {
                Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/delete' -Method Delete -ContentType 'application/json' -Body (@{ model = $m } | ConvertTo-Json -Compress) -TimeoutSec 60 | Out-Null
                Write-Log "  deleted model $m"
            } catch {
                Write-Log "  could not delete model $m : $($_.Exception.Message)"
            }
        }
        if ($started) { Stop-Process -Id $started.Id -Force -ErrorAction SilentlyContinue }
    }
}

# --- Voice models -----------------------------------------------------------
if ($Parts -contains 'voice') {
    Remove-Tree (Join-Path $AppDir 'models\huggingface')
    $recordedHome = Get-InstallInfoValue 'hf_home'
    if ($recordedHome -and (Test-Inside $recordedHome $AppDir)) { Remove-Tree $recordedHome }
    Remove-LegacyVoiceCaches
}

# --- Ollama -------------------------------------------------------------------
if ($Parts -contains 'engine' -and $ownOllama -and (Test-Path -LiteralPath $ownOllama)) {
    Stop-ProcessesUnder $ownOllama
    $unins = Join-Path $ownOllama 'unins000.exe'
    if (Test-Path $unins) {
        $proc = Start-Process -FilePath $unins -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait -PassThru
        Write-Log "  Ollama uninstaller exit $($proc.ExitCode)"
        Start-Sleep -Seconds 2
    }
    Remove-Tree $ownOllama
}

# --- Node.js ------------------------------------------------------------------
if ($Parts -contains 'node') {
    Remove-Tree (Join-Path $AppDir 'tools\node')
}

# --- Orion's runtime ----------------------------------------------------------
if ($Parts -contains 'runtime') {
    Remove-Tree (Join-Path $AppDir 'runtime')
    Remove-Tree (Join-Path $AppDir 'tools\python')
    Remove-Tree (Join-Path $AppDir 'cache')
}

# --- uv -----------------------------------------------------------------------
if ($Parts -contains 'uv') {
    $uv = Get-Record 'installed_uv'
    if ($uv -and (Test-Path -LiteralPath $uv)) {
        $bin = Split-Path -Parent $uv
        foreach ($name in @('uv.exe', 'uvx.exe', 'uvw.exe')) {
            Remove-Item -LiteralPath (Join-Path $bin $name) -Force -ErrorAction SilentlyContinue
        }
        Write-Log "  removed uv from $bin"
    }
}

# --- Personal data ------------------------------------------------------------
if ($Parts -contains 'data') {
    $data = Join-Path $env:USERPROFILE '.orion'
    Remove-Tree $data
}

# --- Leftovers ------------------------------------------------------------------
foreach ($file in @('install.json', 'features.txt', 'setup.log', 'setup-status.json', 'app-settings.json')) {
    Remove-Item -LiteralPath (Join-Path $AppDir $file) -Force -ErrorAction SilentlyContinue
}
foreach ($dir in @('runtime', 'models', 'tools')) {
    $path = Join-Path $AppDir $dir
    if ((Test-Path -LiteralPath $path) -and -not (Get-ChildItem -LiteralPath $path -Force -ErrorAction SilentlyContinue)) {
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    }
}
# Keep the record while anything it describes is still here, so a later
# uninstall knows those parts came from Orion. Parts that were never installed
# do not count: counting them left uninstall.ini (and so the folder) behind.
$kept = @()
if (Test-Path -LiteralPath (Join-Path $AppDir 'runtime')) { $kept += 'runtime' }
if ($Parts -notcontains 'models' -and ((Get-Record 'pulled_models') -or (Get-Record 'ollama_models_dir'))) { $kept += 'models' }
if (Test-Path -LiteralPath (Join-Path $AppDir 'models\huggingface')) { $kept += 'voice' }
if ($ownOllama -and (Test-Path -LiteralPath $ownOllama)) { $kept += 'engine' }
if (Test-Path -LiteralPath (Join-Path $AppDir 'tools\node')) { $kept += 'node' }
$ownUv = Get-Record 'installed_uv'
if ($ownUv -and (Test-Path -LiteralPath $ownUv)) { $kept += 'uv' }
if ($kept.Count -eq 0) { Remove-Item -LiteralPath $RecordFile -Force -ErrorAction SilentlyContinue }
Write-Log "===== done (kept: $($kept -join ', ')) ====="
exit 0
