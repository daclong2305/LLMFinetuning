param([int]$Port = 8765, [string]$Model = 'qwen2.5-coder:3b', [int]$NumGpu = 0, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$demoRoot = $PSScriptRoot
Set-Location -LiteralPath $demoRoot
$demoOllamaExe = Join-Path $demoRoot '.runtime\ollama\ollama.exe'
if (-not (Test-Path -LiteralPath $demoOllamaExe)) {
    $demoInstalledOllama = Get-Command ollama -ErrorAction SilentlyContinue
    if ($demoInstalledOllama) { $demoOllamaExe = $demoInstalledOllama.Source }
    else { throw 'Run setup-demo.ps1 first to install Ollama.' }
}
New-Item -ItemType Directory -Force -Path (Join-Path $demoRoot '.runtime\logs') | Out-Null
$env:OLLAMA_MODELS = Join-Path $demoRoot '.runtime\models'
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_NO_CLOUD = 'true'
$env:TEXT2SQL_MODEL = $Model
$env:TEXT2SQL_NUM_GPU = [string]$NumGpu
try { $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 }
catch {
    $demoOllamaProcess = Start-Process -FilePath $demoOllamaExe -ArgumentList 'serve' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $demoRoot '.runtime\logs\ollama-stdout.log') -RedirectStandardError (Join-Path $demoRoot '.runtime\logs\ollama-stderr.log') -PassThru
    Set-Content -LiteralPath (Join-Path $demoRoot '.runtime\logs\ollama.pid') -Value $demoOllamaProcess.Id
    @{pid=$demoOllamaProcess.Id;path=$demoOllamaProcess.Path;started=$demoOllamaProcess.StartTime.ToUniversalTime().Ticks} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $demoRoot '.runtime\logs\ollama-process.json')
    $demoReady = $false
    for ($demoRetry = 0; $demoRetry -lt 30; $demoRetry++) {
        Start-Sleep -Milliseconds 500
        try { $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2; $demoReady = $true; break }
        catch { }
    }
    if (-not $demoReady) { throw 'Ollama did not start. Check .runtime/logs/ollama-stderr.log.' }
}
$demoModels = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5
if ($Model -notin @($demoModels.models.name)) {
    & $demoOllamaExe pull $Model
    if ($LASTEXITCODE -ne 0) { throw 'Model download failed.' }
}
$demoPython = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $demoPython) { throw 'Python >=3.10 must be installed and on PATH.' }
$demoUrl = "http://127.0.0.1:$Port"
try {
    $demoExisting = Invoke-RestMethod -Uri "$demoUrl/api/info" -TimeoutSec 2
    if (-not $demoExisting.schema.customers -or -not $demoExisting.ollama) { throw 'Port occupied by another service.' }
    if ($demoExisting.ollama.model -ne $Model -or $demoExisting.ollama.compute -ne $(if ($NumGpu -eq 0) {'CPU'} else {'GPU/auto'})) { throw 'Demo is running with another model/compute config. Use another -Port or stop the existing app first.' }
    Write-Output "Demo already running: $demoUrl"
} catch {
    if ($_.Exception.Message -eq 'Port occupied by another service.' -or $_.Exception.Message -like 'Demo is running with another*') { throw }
    $demoAppProcess = Start-Process -FilePath $demoPython -ArgumentList '-m', 'text2sql_demo.server', '--port', $Port -WorkingDirectory $demoRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $demoRoot ".runtime\logs\app-$Port-stdout.log") -RedirectStandardError (Join-Path $demoRoot ".runtime\logs\app-$Port-stderr.log") -PassThru
    Set-Content -LiteralPath (Join-Path $demoRoot '.runtime\logs\app.pid') -Value $demoAppProcess.Id
    @{pid=$demoAppProcess.Id;path=$demoAppProcess.Path;started=$demoAppProcess.StartTime.ToUniversalTime().Ticks} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $demoRoot ".runtime\logs\app-$Port-process.json")
    $demoReady = $false
    for ($demoRetry = 0; $demoRetry -lt 30; $demoRetry++) {
        Start-Sleep -Milliseconds 300
        try { $null = Invoke-RestMethod -Uri "$demoUrl/api/info" -TimeoutSec 3; $demoReady = $true; break }
        catch { }
    }
    if (-not $demoReady) { throw "Demo did not start. Check .runtime/logs/app-$Port-stderr.log." }
    Write-Output "Demo ready: $demoUrl"
}
if (-not $NoBrowser) { Start-Process $demoUrl }
