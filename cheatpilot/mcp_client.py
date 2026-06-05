from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass
from itertools import count
from typing import Any


class MCPError(RuntimeError):
    pass


@dataclass(slots=True)
class MCPTool:
    name: str
    description: str = ""
    input_schema: dict[str, Any] | None = None


class MCPStdioClient:
    """Minimal JSON-RPC stdio client for MCP tool calls."""

    def __init__(self, command: str, args: list[str] | None = None, timeout_seconds: float = 60.0) -> None:
        self.command = command
        self.args = args or []
        self.timeout_seconds = timeout_seconds
        self._ids = count(1)
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._initialized = False

    def __enter__(self) -> "MCPStdioClient":
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def start(self) -> None:
        if self._process is not None:
            return
        self._process = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        self._initialize()

    def close(self) -> None:
        process = self._process
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
        except Exception:
            if process.poll() is None:
                process.kill()
        finally:
            self._process = None
            self._initialized = False

    def list_tools(self) -> list[MCPTool]:
        response = self._request("tools/list", {})
        tools = response.get("tools", [])
        return [
            MCPTool(
                name=str(tool.get("name", "")),
                description=str(tool.get("description", "")),
                input_schema=tool.get("inputSchema"),
            )
            for tool in tools
        ]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        response = self._request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )
        if response.get("isError"):
            raise MCPError(self._extract_content_text(response))
        return self._extract_content(response)

    def _initialize(self) -> None:
        if self._initialized:
            return
        self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "cheatpilot", "version": "0.1.0"},
            },
        )
        self._notify("notifications/initialized", {})
        self._initialized = True

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            process = self._require_process()
            request_id = next(self._ids)
            payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            assert process.stdin is not None
            assert process.stdout is not None
            process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            process.stdin.flush()

            while True:
                line = process.stdout.readline()
                if line == "":
                    stderr = self._read_stderr_nonblocking(process)
                    raise MCPError(f"MCP server exited or closed stdout. {stderr}".strip())
                message = json.loads(line)
                if message.get("id") != request_id:
                    continue
                if "error" in message:
                    raise MCPError(str(message["error"]))
                return dict(message.get("result", {}))

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        process = self._require_process()
        assert process.stdin is not None
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        process.stdin.flush()

    def _require_process(self) -> subprocess.Popen[str]:
        if self._process is None:
            self.start()
        assert self._process is not None
        return self._process

    @staticmethod
    def _extract_content(response: dict[str, Any]) -> Any:
        content = response.get("content", [])
        if not content:
            return response
        if len(content) == 1 and content[0].get("type") == "text":
            text = str(content[0].get("text", ""))
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        return content

    @staticmethod
    def _extract_content_text(response: dict[str, Any]) -> str:
        content = response.get("content", [])
        if not content:
            return str(response)
        return "\n".join(str(item.get("text", item)) for item in content)

    @staticmethod
    def _read_stderr_nonblocking(process: subprocess.Popen[str]) -> str:
        if process.stderr is None:
            return ""
        return ""
