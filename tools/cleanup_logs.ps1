# tools/cleanup_logs.ps1
# Löscht alte Logfiles, damit das Repo nicht vollläuft.
# Safe: wenn Ordner/Files nicht existieren, passiert nichts.

$ErrorActionPreference = "SilentlyContinue"

$projectRoot = Split-Path -Parent $PSScriptRoot
$daysToKeep = 14
$cutoff = (Get-Date).AddDays(-$daysToKeep)

# typische Ordner
$targets = @(
  Join-Path $projectRoot "logs",
  Join-Path $projectRoot "generated"
)

foreach ($t in $targets) {
  if (Test-Path $t) {
    Get-ChildItem -Path $t -Recurse -File -Include *.log |
      Where-Object { $_.LastWriteTime -lt $cutoff } |
      Remove-Item -Force
  }
}

# optional: sehr große logfiles trimmen (>10MB)
Get-ChildItem -Path $projectRoot -Recurse -File -Include *.log |
  Where-Object { $_.Length -gt 10MB } |
  ForEach-Object {
    Clear-Content $_.FullName
  }

Write-Host "Log cleanup done. Kept last $daysToKeep days."
