from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
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
        self._responses: queue.Queue[dict[str, Any] | Exception] = queue.Queue()
        self._stderr_lines: queue.Queue[str] = queue.Queue()
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
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
        self._stdout_thread = threading.Thread(target=self._stdout_reader, args=(self._process,), daemon=True)
        self._stderr_thread = threading.Thread(target=self._stderr_reader, args=(self._process,), daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()
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
            self._stdout_thread = None
            self._stderr_thread = None
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

            deadline = time.monotonic() + self.timeout_seconds
            pending: list[dict[str, Any] | Exception] = []
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        stderr = self._read_stderr_nonblocking(process)
                        raise MCPError(f"MCP request timed out after {self.timeout_seconds:.1f}s: {method}. {stderr}".strip())
                    item = self._responses.get(timeout=remaining)
                    if isinstance(item, Exception):
                        raise MCPError(f"MCP server stdout error: {item}")
                    message = item
                    if message.get("id") != request_id:
                        pending.append(message)
                        continue
                    if "error" in message:
                        raise MCPError(str(message["error"]))
                    return dict(message.get("result", {}))
            except queue.Empty:
                stderr = self._read_stderr_nonblocking(process)
                raise MCPError(f"MCP request timed out after {self.timeout_seconds:.1f}s: {method}. {stderr}".strip())
            finally:
                for item in pending:
                    self._responses.put(item)

    def _stdout_reader(self, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None
        while True:
            line = process.stdout.readline()
            if line == "":
                stderr = self._read_stderr_nonblocking(process)
                self._responses.put(MCPError(f"MCP server exited or closed stdout. {stderr}".strip()))
                return
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                self._responses.put(MCPError(f"invalid MCP JSON response: {exc}; line={line[:240]!r}"))
                continue
            self._responses.put(message)

    def _stderr_reader(self, process: subprocess.Popen[str]) -> None:
        assert process.stderr is not None
        while True:
            line = process.stderr.readline()
            if line == "":
                return
            self._stderr_lines.put(line.rstrip())

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
    def _drain_queue(lines: queue.Queue[str], limit: int = 20) -> list[str]:
        drained: list[str] = []
        while len(drained) < limit:
            try:
                drained.append(lines.get_nowait())
            except queue.Empty:
                break
        return drained

    def _read_stderr_nonblocking(self, process: subprocess.Popen[str]) -> str:
        if process.stderr is None:
            return ""
        lines = self._drain_queue(self._stderr_lines)
        return "\n".join(lines[-10:])
