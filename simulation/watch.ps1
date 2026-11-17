# Watch a simulation run's turn-by-turn output. Usage (from the repo root):
#   .\simulation\watch.ps1                 # the log that changed most recently
#   .\simulation\watch.ps1 pilot-4         # a named run (simulation\runs\pilot-4.log)
param([string]$Run = "")

$runs = Join-Path $PSScriptRoot "runs"
if ($Run) {
    $log = Join-Path $runs "$Run.log"
} else {
    $log = Get-ChildItem $runs -Filter "*.log" | Where-Object { $_.Name -notmatch "judge" } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $log -or -not (Test-Path $log)) { Write-Host "No log found in $runs"; exit 1 }
Write-Host "Watching $log (Ctrl+C to stop)"
Get-Content $log -Wait -Tail 25
