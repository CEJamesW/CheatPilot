from __future__ import annotations

import json
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

    try:
        with MCPStdioClient(config.mcp_command, config.mcp_args or []) as client:
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
