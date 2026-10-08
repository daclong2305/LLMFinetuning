param([int]$Port = 8765, [switch]$StopOllama)
$ErrorActionPreference = 'Stop'
$demoStateFiles = @((Join-Path $PSScriptRoot ".runtime\logs\app-$Port-process.json"))
if ($StopOllama) { $demoStateFiles += Join-Path $PSScriptRoot '.runtime\logs\ollama-process.json' }
foreach ($demoStateFile in $demoStateFiles) {
    if (-not (Test-Path -LiteralPath $demoStateFile)) { Write-Output "No owned process record: $demoStateFile"; continue }
    $demoProcessState = Get-Content -LiteralPath $demoStateFile -Raw | ConvertFrom-Json
    $demoOwnedProcess = Get-Process -Id $demoProcessState.pid -ErrorAction SilentlyContinue
    if ($demoOwnedProcess -and $demoOwnedProcess.Path -eq $demoProcessState.path -and $demoOwnedProcess.StartTime.ToUniversalTime().Ticks -eq $demoProcessState.started) {
        Stop-Process -Id $demoOwnedProcess.Id
        Write-Output "Stopped owned demo process $($demoOwnedProcess.Id)."
    } else { Write-Output 'Process already stopped or identity changed; no action taken.' }
}
