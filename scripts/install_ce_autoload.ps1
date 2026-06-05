$ErrorActionPreference = "Stop"

$cheatEngineAutorun = "C:\Program Files\Cheat Engine\autorun"
$bridgePath = "D:\MCP\cheatengine-mcp-bridge\MCP_Server\ce_mcp_bridge.lua"
$autoloadPath = Join-Path $cheatEngineAutorun "ce_mcp_bridge_autoload.lua"

if (-not (Test-Path -LiteralPath $bridgePath)) {
    throw "Bridge script not found: $bridgePath"
}

if (-not (Test-Path -LiteralPath $cheatEngineAutorun)) {
    throw "Cheat Engine autorun directory not found: $cheatEngineAutorun"
}

$content = @"
local bridgePath = [[$bridgePath]]

if not io.open(bridgePath, "r") then
  print("[CE MCP] Bridge script not found: " .. bridgePath)
  return
end

local ok, err = pcall(dofile, bridgePath)
if not ok then
  print("[CE MCP] Failed to autoload bridge: " .. tostring(err))
end
"@

Set-Content -LiteralPath $autoloadPath -Value $content -Encoding UTF8
Write-Host "Installed Cheat Engine MCP autoload script: $autoloadPath"
