$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$stateFile = Join-Path $projectRoot '.runtime\local-services.json'
if (-not (Test-Path -LiteralPath $stateFile)) {
    Write-Output 'No local service state file found.'
    return
}

$state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
if ($state.project -ne $projectRoot) {
    throw 'local_service_state_project_mismatch'
}

$entries = @(
    foreach ($id in @($state.schedulerPids) + @($state.serverPids)) {
        if (-not $id) { continue }
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
        if (-not $process) { continue }
        $isProjectPython = $process.Name -eq 'python.exe' -and (
            $process.ExecutablePath -like "$projectRoot*" -or
            $process.CommandLine -like "*$projectRoot*"
        )
        $isLocalCommand = $process.CommandLine -match 'manage\.py.*(runserver|run_scheduler)'
        if ($isProjectPython -and $isLocalCommand) {
            [pscustomobject]@{ Id = [int]$id; ParentProcessId = [int]$process.ParentProcessId }
        }
    }
)

$allProcesses = @(Get-CimInstance Win32_Process)
$rootIds = @($entries.Id)
$entries += @(
    $allProcesses | Where-Object {
        $_.Name -eq 'python.exe' -and
        $_.ParentProcessId -in $rootIds -and
        $_.CommandLine -match 'manage\.py.*(runserver|run_scheduler)'
    } | ForEach-Object {
        [pscustomobject]@{ Id = [int]$_.ProcessId; ParentProcessId = [int]$_.ParentProcessId }
    }
)

foreach ($entry in ($entries | Sort-Object ParentProcessId -Descending | Select-Object -Unique Id)) {
    Stop-Process -Id $entry.Id -Force -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $stateFile -Force -ErrorAction SilentlyContinue
Write-Output "Stopped local services: $($entries.Id -join ',')"
