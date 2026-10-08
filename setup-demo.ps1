param([string]$Model = 'qwen2.5-coder:3b')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$demoRelease = 'v0.35.1'
$demoExpectedHash = 'DC50B9CA7F9023C86525012632CD1615B093D0407987444A7F62ECAB617E8E93'
$demoRuntimeDir = Join-Path $PSScriptRoot '.runtime\ollama'
$demoDownloadDir = Join-Path $PSScriptRoot '.runtime\downloads'
New-Item -ItemType Directory -Force -Path $demoRuntimeDir,$demoDownloadDir | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $demoRuntimeDir 'ollama.exe'))) {
    $demoArchive = Join-Path $demoDownloadDir 'ollama-windows-amd64.zip'
    Write-Output 'Downloading official Ollama portable runtime (about 1.5 GB)...'
    Invoke-WebRequest -Uri "https://github.com/ollama/ollama/releases/download/$demoRelease/ollama-windows-amd64.zip" -OutFile $demoArchive
    if ((Get-FileHash -LiteralPath $demoArchive -Algorithm SHA256).Hash -ne $demoExpectedHash) { throw 'SHA256 mismatch. Archive not extracted.' }
    Expand-Archive -LiteralPath $demoArchive -DestinationPath $demoRuntimeDir -Force
}
& (Join-Path $PSScriptRoot 'start-demo.ps1') -Model $Model -NoBrowser
