$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$cheatEngineAutorun = "C:\Program Files\Cheat Engine\autorun"
$bridgePath = Join-Path $projectRoot "runtime\ce_mcp\ce_mcp_bridge.lua"
$autoloadPath = Join-Path $cheatEngineAutorun "cheatpilot_mcp_autoload.lua"

if (-not (Test-Path -LiteralPath $bridgePath)) {
    throw "Bridge script not found: $bridgePath"
}

if (-not (Test-Path -LiteralPath $cheatEngineAutorun)) {
    throw "Cheat Engine autorun directory not found: $cheatEngineAutorun"
}

$content = @"
local bridgePath = [[$bridgePath]]

if not io.open(bridgePath, "r") then
  print("[CheatPilot MCP] Bridge script not found: " .. bridgePath)
  return
end

local ok, err = pcall(dofile, bridgePath)
if not ok then
  print("[CheatPilot MCP] Failed to autoload bridge: " .. tostring(err))
end
"@

Set-Content -LiteralPath $autoloadPath -Value $content -Encoding UTF8
Write-Host "Installed CheatPilot MCP autoload script: $autoloadPath"
