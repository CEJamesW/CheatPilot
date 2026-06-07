from __future__ import annotations

import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cheatpilot.config import PROJECT_ROOT
from cheatpilot.models import ActionResult, ActionType, AgentAction


@dataclass(slots=True)
class LocalToolExecutor:
    """Local filesystem and command tools for the tool-use agent."""

    root: Path = PROJECT_ROOT
    default_timeout_seconds: int = 60
    max_output_chars: int = 24000
    max_file_chars: int = 80000

    def execute(self, action: AgentAction) -> ActionResult:
        try:
            if action.type == ActionType.THINK:
                return self._think(action)
            if action.type == ActionType.LIST_FILES:
                return self._list_files(action)
            if action.type == ActionType.READ_FILE:
                return self._read_file(action)
            if action.type == ActionType.WRITE_FILE:
                return self._write_file(action)
            if action.type == ActionType.RUN_COMMAND:
                return self._run_command(action)
        except (OSError, UnicodeError, subprocess.SubprocessError, ValueError, KeyError) as exc:
            return ActionResult(action=action, ok=False, message=f"Local tool error: {exc}", data={"error": str(exc)})
        return ActionResult(action=action, ok=False, message=f"Unhandled local action: {action.type}", data={})

    def _think(self, action: AgentAction) -> ActionResult:
        thought = str(action.arguments.get("thought") or action.arguments.get("summary") or "").strip()
        next_action = str(action.arguments.get("next_action") or "").strip()
        message = thought or "已记录当前思考。"
        if next_action:
            message += f" 下一步：{next_action}"
        return ActionResult(
            action=action,
            ok=True,
            message=message,
            data={"thought": thought, "next_action": next_action},
        )

    def _list_files(self, action: AgentAction) -> ActionResult:
        base = self._resolve_path(action.arguments.get("path") or ".")
        pattern = str(action.arguments.get("pattern") or "*")
        recursive = bool(action.arguments.get("recursive", False))
        include_hidden = bool(action.arguments.get("include_hidden", False))
        limit = int(action.arguments.get("limit") or 200)

        iterator = base.rglob(pattern) if recursive else base.glob(pattern)
        items: list[dict[str, Any]] = []
        for item in iterator:
            if not include_hidden and any(part.startswith(".") for part in item.relative_to(base).parts):
                continue
            try:
                stat = item.stat()
            except OSError:
                continue
            items.append(
                {
                    "path": str(item),
                    "relative_path": str(item.relative_to(self.root)) if _is_relative_to(item, self.root) else str(item),
                    "type": "dir" if item.is_dir() else "file",
                    "size": stat.st_size,
                }
            )
            if len(items) >= limit:
                break

        return ActionResult(
            action=action,
            ok=True,
            message=f"列出 {base} 下 {len(items)} 个项目。",
            data={"path": str(base), "pattern": pattern, "recursive": recursive, "items": items},
        )

    def _read_file(self, action: AgentAction) -> ActionResult:
        path = self._resolve_path(action.arguments["path"])
        max_chars = int(action.arguments.get("max_chars") or self.max_file_chars)
        encoding = str(action.arguments.get("encoding") or "utf-8")
        text = path.read_text(encoding=encoding, errors="replace")
        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars]
        return ActionResult(
            action=action,
            ok=True,
            message=f"已读取文件 {path}。",
            data={
                "path": str(path),
                "content": text,
                "truncated": truncated,
                "encoding": encoding,
                "size": path.stat().st_size,
            },
        )

    def _write_file(self, action: AgentAction) -> ActionResult:
        path = self._resolve_path(action.arguments["path"])
        content = str(action.arguments.get("content") or "")
        encoding = str(action.arguments.get("encoding") or "utf-8")
        append = bool(action.arguments.get("append", False))
        create_dirs = bool(action.arguments.get("create_dirs", True))
        if create_dirs:
            path.parent.mkdir(parents=True, exist_ok=True)
        if append:
            with path.open("a", encoding=encoding, errors="replace") as handle:
                handle.write(content)
        else:
            path.write_text(content, encoding=encoding, errors="replace")
        return ActionResult(
            action=action,
            ok=True,
            message=f"已{'追加' if append else '写入'}文件 {path}。",
            data={"path": str(path), "bytes": len(content.encode(encoding, errors="replace")), "append": append},
        )

    def _run_command(self, action: AgentAction) -> ActionResult:
        command = str(action.arguments["command"])
        cwd = self._resolve_path(action.arguments.get("cwd") or self.root)
        timeout_seconds = int(action.arguments.get("timeout_seconds") or self.default_timeout_seconds)
        shell = str(action.arguments.get("shell") or "powershell").strip().lower() or "powershell"
        shell_commands = {
            "powershell": ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            "pwsh": ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            "cmd": ["cmd", "/c", command],
            "bash": ["bash", "-lc", command],
            "sh": ["sh", "-lc", command],
        }
        if shell not in shell_commands:
            return ActionResult(
                action=action,
                ok=False,
                message=f"Unsupported shell: {shell}.",
                data={"command": command, "cwd": str(cwd), "shell": shell, "error": "unsupported_shell"},
            )

        argv = shell_commands[shell]
        executable = shutil.which(argv[0])
        if executable is None:
            return ActionResult(
                action=action,
                ok=False,
                message=f"Requested shell is not available: {shell}.",
                data={"command": command, "cwd": str(cwd), "shell": shell, "error": "shell_unavailable"},
            )
        argv[0] = executable

        try:
            completed = subprocess.run(
                argv,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            stdout, stdout_truncated = _truncate(_decode_output(exc.stdout), self.max_output_chars)
            stderr, stderr_truncated = _truncate(_decode_output(exc.stderr), self.max_output_chars)
            return ActionResult(
                action=action,
                ok=False,
                message=f"Command timed out after {timeout_seconds} seconds.",
                data={
                    "command": command,
                    "cwd": str(cwd),
                    "shell": shell,
                    "error": "timeout",
                    "stdout": stdout,
                    "stderr": stderr,
                    "stdout_truncated": stdout_truncated,
                    "stderr_truncated": stderr_truncated,
                },
            )
        except OSError as exc:
            return ActionResult(
                action=action,
                ok=False,
                message=f"Failed to run command with shell {shell}: {exc}",
                data={"command": command, "cwd": str(cwd), "shell": shell, "error": str(exc)},
            )

        stdout, stdout_truncated = _truncate(completed.stdout, self.max_output_chars)
        stderr, stderr_truncated = _truncate(completed.stderr, self.max_output_chars)
        ok = completed.returncode == 0
        return ActionResult(
            action=action,
            ok=ok,
            message=f"命令执行完成，退出码 {completed.returncode}。",
            data={
                "command": command,
                "cwd": str(cwd),
                "shell": shell,
                "returncode": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
            },
        )

    def _resolve_path(self, value: Any) -> Path:
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = self.root / path
        return path.resolve()


def _truncate(value: str, max_chars: int) -> tuple[str, bool]:
    if len(value) <= max_chars:
        return value, False
    return value[:max_chars], True


def _decode_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True
