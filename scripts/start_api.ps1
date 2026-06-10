$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
python -m uvicorn cheatpilot.api:app --host 127.0.0.1 --port 8765
