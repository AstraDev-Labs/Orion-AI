$ErrorActionPreference = "Stop"
$repo = "ggerganov/llama.cpp"
$releases = Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/releases/latest"

$asset = $releases.assets | Where-Object { $_.name -match "cudart-cu12" -and $_.name -match "win" } | Select-Object -First 1

if (-not $asset) {
    Write-Error "Could not find a CUDA 12 Windows release."
    exit 1
}

$downloadUrl = $asset.browser_download_url
$zipFile = "C:\Users\Tharun\Documents\Orion-main\llama.cpp\llama-bin.zip"
$destFolder = "C:\Users\Tharun\Documents\Orion-main\llama.cpp\bin"

Write-Host "Downloading $($asset.name)..."
Invoke-WebRequest -Uri $downloadUrl -OutFile $zipFile

Write-Host "Extracting to $destFolder..."
if (!(Test-Path -Path $destFolder)) {
    New-Item -ItemType Directory -Path $destFolder | Out-Null
}
Expand-Archive -Path $zipFile -DestinationPath $destFolder -Force

Write-Host "Cleaning up zip file..."
Remove-Item $zipFile

Write-Host "Done! llama-server.exe is ready in $destFolder."
