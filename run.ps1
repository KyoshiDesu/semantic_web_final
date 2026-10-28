# Starts AutoGrade-RDF: one local server for the API (/api) and the web pages (web/). Usage: .\run.ps1 [-Port 8000]
param([int]$Port = 8000)
$ErrorActionPreference = "Stop"
if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
  throw "conda not found: install Miniconda and create the semantic_web env (README, Setup), or use the Anaconda PowerShell Prompt"
}

function Invoke-Autograde {
  conda run --no-capture-output -n semantic_web python -m autograde @args
  if ($LASTEXITCODE) { exit $LASTEXITCODE }
}

Push-Location $PSScriptRoot
try {
  $dbDir = if ($env:AUTOGRADE_DB_DIR) { $env:AUTOGRADE_DB_DIR } else { "db" }
  # The first start fills the database from data/ (the demo course); later starts keep what was entered in the app.
  if (-not (Test-Path (Join-Path $dbDir "autograde.sqlite"))) { Invoke-Autograde db import }
  Invoke-Autograde serve --port $Port
} finally {
  Pop-Location
}
