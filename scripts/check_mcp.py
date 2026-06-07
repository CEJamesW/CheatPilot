from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cheatpilot.config import CheatPilotConfig
from cheatpilot.mcp_client import MCPError, MCPStdioClient


def main() -> int:
    config = CheatPilotConfig.from_env()
    print("CheatPilot MCP check")
    print(f"Server: {config.mcp_command} {' '.join(config.mcp_args or [])}")

    command_path = shutil.which(config.mcp_command) or config.mcp_command
    if not Path(command_path).exists() and shutil.which(config.mcp_command) is None:
        print(f"MCP check failed: Python executable not found: {config.mcp_command}")
        print("Set CHEATPILOT_MCP_COMMAND to a Python executable that has runtime/ce_mcp/requirements.txt installed.")
        return 1

    for arg in config.mcp_args or []:
        if arg.lower().endswith(".py") and not Path(arg).exists():
            print(f"MCP check failed: MCP server script not found: {arg}")
            print("Run python scripts\\bootstrap_ce_mcp.py, or set CHEATPILOT_MCP_ARGS to runtime\\ce_mcp\\mcp_cheatengine.py.")
            return 1

    try:
        with MCPStdioClient(config.mcp_command, config.mcp_args or [], timeout_seconds=config.mcp_timeout_seconds) as client:
            ping = client.call_tool("ping", {})
            print("ping:")
            print(json.dumps(ping, ensure_ascii=False, indent=2))

            process_info = client.call_tool("get_process_info", {})
            print("process_info:")
            print(json.dumps(process_info, ensure_ascii=False, indent=2))
        return 0
    except MCPError as exc:
        print(f"MCP check failed: {exc}")
        print(
            "Start Cheat Engine and make sure the CE Lua bridge is running. "
            "If another MCP client is already connected to the CE bridge, close it before running this check."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
