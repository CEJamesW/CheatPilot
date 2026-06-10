from __future__ import annotations

import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_LLM_BASE_URL = "https://ai.saurlax.com/v1"
DEFAULT_LLM_MODEL = "mimo-v2.5-pro"
DEFAULT_LLM_TIMEOUT_SECONDS = 45.0
DEFAULT_LLM_MAX_RETRIES = 3
DEFAULT_MAX_TOOL_ROUNDS = 10
DEFAULT_MAX_HISTORY_MESSAGES = 24
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MCP_COMMAND = sys.executable
DEFAULT_MCP_ARGS = [str(PROJECT_ROOT / "runtime" / "ce_mcp" / "mcp_cheatengine.py")]
DEFAULT_MCP_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class CheatPilotConfig:
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_api_key: str = ""
    llm_model: str = DEFAULT_LLM_MODEL
    llm_timeout_seconds: float = DEFAULT_LLM_TIMEOUT_SECONDS
    llm_max_retries: int = DEFAULT_LLM_MAX_RETRIES
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS
    max_history_messages: int = DEFAULT_MAX_HISTORY_MESSAGES
    planner: str = "llm"
    mcp_command: str = DEFAULT_MCP_COMMAND
    mcp_args: list[str] | None = None
    mcp_timeout_seconds: float = DEFAULT_MCP_TIMEOUT_SECONDS
    allow_lua_actions: bool = False
    value_type: str = "dword"
    max_scan_results: int = 25

    @classmethod
    def from_env(cls) -> "CheatPilotConfig":
        load_dotenv(PROJECT_ROOT / ".env")
        return cls(
            llm_base_url=_normalize_openai_base_url(os.getenv("CHEATPILOT_LLM_BASE_URL", DEFAULT_LLM_BASE_URL)),
            llm_api_key=os.getenv("CHEATPILOT_LLM_API_KEY", ""),
            llm_model=os.getenv("CHEATPILOT_LLM_MODEL", DEFAULT_LLM_MODEL),
            llm_timeout_seconds=_parse_float(os.getenv("CHEATPILOT_LLM_TIMEOUT_SECONDS"), DEFAULT_LLM_TIMEOUT_SECONDS),
            llm_max_retries=_parse_int(os.getenv("CHEATPILOT_LLM_MAX_RETRIES"), DEFAULT_LLM_MAX_RETRIES),
            max_tool_rounds=_parse_positive_int(os.getenv("CHEATPILOT_MAX_TOOL_ROUNDS"), DEFAULT_MAX_TOOL_ROUNDS),
            max_history_messages=_parse_positive_int(os.getenv("CHEATPILOT_MAX_HISTORY_MESSAGES"), DEFAULT_MAX_HISTORY_MESSAGES),
            planner=os.getenv("CHEATPILOT_PLANNER", "llm").lower(),
            mcp_command=os.getenv("CHEATPILOT_MCP_COMMAND", DEFAULT_MCP_COMMAND),
            mcp_args=_normalize_mcp_args(_parse_args(os.getenv("CHEATPILOT_MCP_ARGS"), DEFAULT_MCP_ARGS)),
            mcp_timeout_seconds=_parse_float(os.getenv("CHEATPILOT_MCP_TIMEOUT_SECONDS"), DEFAULT_MCP_TIMEOUT_SECONDS),
            allow_lua_actions=os.getenv("CHEATPILOT_ALLOW_LUA", "").lower() in {"1", "true", "yes", "on"},
            value_type=os.getenv("CHEATPILOT_VALUE_TYPE", "dword"),
            max_scan_results=_parse_int(os.getenv("CHEATPILOT_MAX_SCAN_RESULTS"), 25),
        )


def _parse_args(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return list(default)
    if ";" in value:
        return [item.strip() for item in value.split(";") if item.strip()]
    return shlex.split(value, posix=False)


def _normalize_mcp_args(args: list[str]) -> list[str]:
    normalized: list[str] = []
    for arg in args:
        path = Path(arg)
        looks_like_path = path.suffix.lower() == ".py" or "\\" in arg or "/" in arg
        if looks_like_path and not path.is_absolute():
            normalized.append(str((PROJECT_ROOT / path).resolve()))
        else:
            normalized.append(arg)
    return normalized


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _normalize_openai_base_url(value: str) -> str:
    normalized = value.rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme and parsed.netloc and parsed.path in {"", "/"}:
        return f"{normalized}/v1"
    return normalized


def _parse_int(value: str | None, default: int) -> int:
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _parse_positive_int(value: str | None, default: int) -> int:
    parsed = _parse_int(value, default)
    return parsed if parsed > 0 else default


def _parse_float(value: str | None, default: float) -> float:
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default
