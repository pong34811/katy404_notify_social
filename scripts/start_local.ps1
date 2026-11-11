$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$runtimeDir = Join-Path $projectRoot '.runtime'
$stateFile = Join-Path $runtimeDir 'local-services.json'

if (-not (Test-Path -LiteralPath $python)) {
    throw 'project_python_not_found'
}
if (-not (Test-Path -LiteralPath $runtimeDir)) {
    New-Item -ItemType Directory -Path $runtimeDir | Out-Null
}

$gateOutput = @(& $python manage.py shell -v 0 -c "import os; from social.models import Page; print('READY' if os.getenv('LIVE_PUBLISH','0') == '1' and Page.objects.filter(auto_publish=True).exists() else 'PAUSED')")
if ($LASTEXITCODE -ne 0 -or $gateOutput[-1].Trim() -ne 'READY') {
    throw 'publishing_gates_closed_check_LIVE_PUBLISH_and_Page_auto_publish'
}

$serverUrl = 'http://127.0.0.1:8000/admin/login/'
$serverReady = $false
try {
    $response = Invoke-WebRequest -Uri $serverUrl -UseBasicParsing -TimeoutSec 3
    $serverReady = $response.StatusCode -eq 200
} catch {
    $serverReady = $false
}

$processes = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'python.exe' -and
    $_.ExecutablePath -like "$projectRoot*" -and
    $_.CommandLine -match 'manage\.py'
})
$serverPids = @($processes | Where-Object { $_.CommandLine -match 'runserver' } | ForEach-Object ProcessId)
$schedulerPids = @($processes | Where-Object { $_.CommandLine -match 'run_scheduler' } | ForEach-Object ProcessId)
$previousState = $null
if (Test-Path -LiteralPath $stateFile) {
    $previousState = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
    if ($previousState.project -ne $projectRoot) {
        throw 'local_service_state_project_mismatch'
    }
}
$ownedServerPids = @($processes | Where-Object {
    $_.ProcessId -in @($previousState.serverPids) -and $_.CommandLine -match 'runserver'
} | ForEach-Object ProcessId)
$ownedSchedulerPids = @($processes | Where-Object {
    $_.ProcessId -in @($previousState.schedulerPids) -and $_.CommandLine -match 'run_scheduler'
} | ForEach-Object ProcessId)
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

if (-not $serverReady) {
    $stdout = Join-Path $runtimeDir "webserver-$stamp.out.log"
    $stderr = Join-Path $runtimeDir "webserver-$stamp.err.log"
    $server = Start-Process -FilePath $python `
        -ArgumentList 'manage.py runserver 127.0.0.1:8000 --noreload' `
        -WorkingDirectory $projectRoot -WindowStyle Hidden `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    $serverPids = @($server.Id)
    $ownedServerPids += $server.Id
    Start-Sleep -Seconds 2
    $response = Invoke-WebRequest -Uri $serverUrl -UseBasicParsing -TimeoutSec 8
    if ($response.StatusCode -ne 200) {
        throw 'webserver_start_failed'
    }
}

if ($schedulerPids.Count -eq 0) {
    $stdout = Join-Path $runtimeDir "scheduler-$stamp.out.log"
    $stderr = Join-Path $runtimeDir "scheduler-$stamp.err.log"
    $scheduler = Start-Process -FilePath $python `
        -ArgumentList 'manage.py run_scheduler --publish --include-unscheduled --process-limit 1' `
        -WorkingDirectory $projectRoot -WindowStyle Hidden `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    $schedulerPids = @($scheduler.Id)
    $ownedSchedulerPids += $scheduler.Id
}

if ($ownedServerPids.Count -or $ownedSchedulerPids.Count) {
    [ordered]@{
        project = $projectRoot
        serverPids = @($ownedServerPids | Select-Object -Unique)
        schedulerPids = @($ownedSchedulerPids | Select-Object -Unique)
        startedAt = (Get-Date).ToString('o')
    } | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding utf8
}

Write-Output "Web server: $serverUrl"
Write-Output "Scheduler PIDs: $($schedulerPids -join ',')"
Write-Output 'Scheduler scans immediately, then every hour; publishes one item per minute and skips duplicates.'
