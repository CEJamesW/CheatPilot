from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from cheatpilot.config import DEFAULT_MAX_HISTORY_MESSAGES, DEFAULT_MAX_TOOL_ROUNDS
from cheatpilot.executors.base import MemoryExecutor
from cheatpilot.models import ActionResult, ActionType, AgentAction, AgentPlan, AgentResponse


@dataclass(slots=True)
class ToolUseChatAgent:
    """OpenAI-compatible tool-calling agent backed by CheatPilot actions."""

    executor: MemoryExecutor
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 8.0
    max_retries: int = 3
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS
    max_history_messages: int = DEFAULT_MAX_HISTORY_MESSAGES
    _conversation: list[dict[str, str]] = field(default_factory=list, init=False, repr=False)
    _handle_lock: Any = field(default_factory=threading.RLock, init=False, repr=False)

    def handle(self, message: str) -> AgentResponse:
        with self._handle_lock:
            return self._handle_locked(message)

    def _handle_locked(self, message: str) -> AgentResponse:
        normalized = message.strip()
        if not normalized:
            raise ValueError("message cannot be empty")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt()},
            *self._history_messages(),
            {"role": "user", "content": normalized},
        ]
        actions: list[AgentAction] = []
        results: list[ActionResult] = []
        assistant_message: str | None = None

        for _round in range(self.max_tool_rounds):
            try:
                response = self._chat(messages, tools=tool_schemas())
            except Exception as exc:
                if not results:
                    raise
                assistant_message = _fallback_assistant_message(results, exc)
                break
            choice = _normalize_assistant_message(_assistant_message_from_response(response))
            messages.append(choice)
            tool_calls = _normalize_tool_calls(choice)
            if not tool_calls:
                assistant_message = str(choice.get("content") or "我已处理完这轮请求。")
                if not actions:
                    actions.append(
                        AgentAction(
                            type=ActionType.EXPLAIN,
                            arguments={"text": assistant_message},
                            reason="The model answered without tool calls.",
                        )
                    )
                    results.append(ActionResult(action=actions[-1], ok=True, message=assistant_message, data={}))
                break

            stop_tool_loop = False
            for index, tool_call in enumerate(tool_calls):
                function = tool_call.get("function") or {}
                name = str(function.get("name") or "")
                arguments, parse_error = _parse_tool_arguments(function.get("arguments"))
                action = _action_from_tool_call(name, arguments)
                if parse_error:
                    result = ActionResult(
                        action=action,
                        ok=False,
                        message=f"工具参数格式错误：{parse_error}",
                        data={
                            "tool_argument_error": True,
                            "error": parse_error,
                            "next_step": "请用该工具 schema 要求的 JSON object 参数重新调用工具。",
                        },
                    )
                else:
                    result = self.executor.execute(action)
                actions.append(action)
                results.append(result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id"),
                        "name": name,
                        "content": json.dumps(result_to_tool_payload(result), ensure_ascii=False),
                    }
                )
                if result.data.get("fatal") or (action.type == ActionType.ATTACH_PROCESS and not result.ok):
                    _append_skipped_tool_results(messages, tool_calls[index + 1 :])
                    stop_tool_loop = True
                    break
            if stop_tool_loop or (
                results and (results[-1].data.get("fatal") or results[-1].action.type == ActionType.ATTACH_PROCESS and not results[-1].ok)
            ):
                break

        if assistant_message is None:
            try:
                assistant_message = self._finalize_from_tool_results(messages)
            except Exception as exc:
                if not results:
                    raise
                assistant_message = _fallback_assistant_message(results, exc)

        if not actions:
            actions.append(
                AgentAction(
                    type=ActionType.EXPLAIN,
                    arguments={"text": assistant_message},
                    reason="No tool call was produced.",
                )
            )
            results.append(ActionResult(action=actions[-1], ok=True, message=assistant_message, data={}))

        self._remember_turn(normalized, assistant_message)

        return AgentResponse(
            plan=AgentPlan.create(original_message=normalized, actions=actions, summary=f"Tool-use agent ran {len(actions)} action(s)."),
            results=results,
            assistant_message=assistant_message,
        )

    def close(self) -> None:
        close = getattr(self.executor, "close", None)
        if callable(close):
            close()

    def _chat(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if not self.base_url or not self.api_key:
            raise RuntimeError("CHEATPILOT_LLM_BASE_URL and CHEATPILOT_LLM_API_KEY are required")
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=body,
            method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    decoded = json.loads(response.read().decode("utf-8"))
                    if not isinstance(decoded, dict):
                        raise RuntimeError(f"LLM 返回格式无效：期望 JSON object，实际 {type(decoded).__name__}")
                    return decoded
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"LLM 返回不是合法 JSON：{exc.msg} at char {exc.pos}") from exc
            except urllib.error.HTTPError as exc:
                if not _is_retryable_http_error(exc) or attempt >= self.max_retries:
                    raise RuntimeError(f"LLM tool-use request failed: {exc}") from exc
                time.sleep(_retry_delay_seconds(attempt, exc))
            except (TimeoutError, urllib.error.URLError) as exc:
                if attempt >= self.max_retries:
                    raise RuntimeError(f"LLM tool-use request failed after {self.max_retries + 1} attempts: {exc}") from exc
                time.sleep(_retry_delay_seconds(attempt))
        raise RuntimeError("LLM tool-use request failed: retry loop exhausted")

    def _finalize_from_tool_results(self, messages: list[dict[str, Any]]) -> str:
        final_messages = [
            *messages,
            {
                "role": "system",
                "content": (
                    "请根据本轮用户请求和已经返回的工具结果，用中文给用户一个简洁最终回复。"
                    "不要再调用工具；只能基于工具观察到的事实回答，不要凭空捏造。"
                    "如工具结果要求用户补充当前值、改变数值或继续提供新值，就明确告诉用户下一步要做什么。"
                ),
            },
        ]
        response = self._chat(final_messages)
        choice = _assistant_message_from_response(response)
        return str(choice.get("content") or "工具调用已完成，但模型没有返回最终文本。")

    def _history_messages(self) -> list[dict[str, str]]:
        return [dict(item) for item in self._conversation[-self.max_history_messages :]]

    def _remember_turn(self, user_message: str, assistant_message: str) -> None:
        self._conversation.append({"role": "user", "content": user_message})
        self._conversation.append({"role": "assistant", "content": assistant_message})
        if len(self._conversation) > self.max_history_messages:
            self._conversation = self._conversation[-self.max_history_messages :]

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are CheatPilot, a natural-language memory modification agent. "
            "You run an observe-think-act loop. Every user message reaches you first; decide what facts are missing, then either ask the user or call tools. "
            "Use real tools only: memory operations must go through Cheat Engine MCP, and local file/command work must go through local tools. Never invent tool results. "
            "Reply in Chinese unless the user asks otherwise. "
            "Use think to record a short operational summary before non-trivial tool work, but keep it concise and action-oriented. "
            "Treat words such as hook, attach, connect, 打开, 连接, 附加到, and hook住 as requests to call attach_process when a target process is named. "
            "For numeric memory changes, do not guess the current value. If the user only gives the target value, ask for the current visible value. "
            "When current value is known, choose a short stable label, then use high-level CheatPilot tools: attach_process if needed, scan_exact_value, write_value, read_value, and print_base_address when requested. "
            "If scan observations show multiple candidates, ask the user to change that same value in the target process and report the new value; after they report it, use next_scan. "
            "If exactly one active scan session exists and the user reports only a number, continue that session with next_scan. "
            "Keep labels consistent across turns. Do not switch between labels for the same value. "
            "Use list_ce_tools to inspect available raw Cheat Engine MCP tools when you are unsure which low-level MCP tool exists or what arguments it takes. "
            "Use ce_mcp_call for low-level Cheat Engine MCP inspection or one-off MCP tools when the high-level tools are not enough. "
            "When the target process name is ambiguous or may be a window/app name rather than an executable name, use list_processes to find real process candidates, then attach_process with the exact process name or PID. "
            "For reset/status requests, call reset_session/session_status instead of answering from memory. "
            "For string replacement, call scan_string, write_string, then read_string when verification is useful. "
            "For explicit byte patches, call write_bytes only when the user provides an explicit address and byte sequence. "
            "Use list_files/list_processes/read_file/write_file/run_command when the user asks you to inspect the local machine, edit project files, or run commands. "
            "For run_command, choose shell='powershell' for Windows commands, shell='cmd' for cmd builtins, or shell='bash' when the user explicitly asks for bash-style commands. "
            "For casual chat or help, answer normally without tools. "
            "Do not claim success unless a tool result confirms it."
        )


def tool_schemas() -> list[dict[str, Any]]:
    return [
        _tool(
            "think",
            "Record a concise operational thought and next action before meaningful tool work.",
            {"thought": {"type": "string"}, "next_action": {"type": "string"}},
            ["thought"],
        ),
        _tool("attach_process", "Attach Cheat Engine to a process by exact process name or PID.", {"process": {"type": "string"}, "pid": {"type": "integer"}}),
        _tool("get_process_info", "Get attached process information.", {}),
        _tool("session_status", "Show saved scan session status.", {"label": {"type": "string"}}),
        _tool("reset_session", "Clear saved CheatPilot scan session.", {}),
        _tool(
            "scan_exact_value",
            "Scan for an exact numeric value.",
            {"label": {"type": "string"}, "value": _numeric_value_schema(), "value_type": {"type": "string"}},
            ["label", "value"],
        ),
        _tool(
            "next_scan",
            "Filter previous scan by a new value.",
            {"label": {"type": "string"}, "value": _numeric_value_schema(), "scan_type": {"type": "string"}},
            ["value"],
        ),
        _tool(
            "write_value",
            "Write a numeric value to a unique known address or explicit address.",
            {"label": {"type": "string"}, "value": _numeric_value_schema(), "address": {"type": "string"}, "value_type": {"type": "string"}},
            ["value"],
        ),
        _tool("print_base_address", "Print the unique address/base address for a label.", {"label": {"type": "string"}}),
        _tool("read_value", "Read a numeric value from a known or explicit address.", {"label": {"type": "string"}, "address": {"type": "string"}, "value_type": {"type": "string"}}),
        _tool(
            "scan_string",
            "Scan for a string value.",
            {"label": {"type": "string"}, "value": {"type": "string"}, "wide": {"type": "boolean"}, "limit": {"type": "integer"}},
            ["label", "value"],
        ),
        _tool(
            "read_string",
            "Read a string from a known or explicit address.",
            {"label": {"type": "string"}, "address": {"type": "string"}, "max_length": {"type": "integer"}, "wide": {"type": "boolean"}},
        ),
        _tool(
            "write_string",
            "Write a string to a unique known address or explicit address.",
            {"label": {"type": "string"}, "address": {"type": "string"}, "value": {"type": "string"}, "wide": {"type": "boolean"}},
            ["value"],
        ),
        _tool(
            "scan_aob",
            "Scan for an Array of Bytes pattern.",
            {"pattern": {"type": "string"}, "protection": {"type": "string"}, "limit": {"type": "integer"}},
            ["pattern"],
        ),
        _tool(
            "write_bytes",
            "Write raw bytes to an explicit address. The bytes field can be a hex string such as '90 90' or an integer array.",
            {"address": {"type": "string"}, "bytes": _byte_sequence_schema()},
            ["address", "bytes"],
        ),
        _tool(
            "evaluate_lua",
            "Execute benign Cheat Engine Lua automation if enabled by configuration.",
            {"code": {"type": "string"}},
            ["code"],
        ),
        _tool(
            "list_ce_tools",
            "List available raw Cheat Engine MCP tools and their input schemas. Use this before ce_mcp_call when unsure.",
            {"query": {"type": "string"}, "limit": {"type": "integer"}},
        ),
        _tool(
            "ce_mcp_call",
            "Call a raw Cheat Engine MCP tool by name and return its real result.",
            {"tool_name": {"type": "string"}, "arguments": {"type": "object"}},
            ["tool_name", "arguments"],
        ),
        _tool(
            "list_files",
            "List files under a directory for local project inspection.",
            {
                "path": {"type": "string"},
                "pattern": {"type": "string"},
                "recursive": {"type": "boolean"},
                "include_hidden": {"type": "boolean"},
                "limit": {"type": "integer"},
            },
        ),
        _tool(
            "list_processes",
            "List local process candidates by name, path, PID, or command line before attaching through Cheat Engine MCP.",
            {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
                "include_command_line": {"type": "boolean"},
                "timeout_seconds": {"type": "integer"},
            },
        ),
        _tool(
            "read_file",
            "Read a local text file.",
            {"path": {"type": "string"}, "max_chars": {"type": "integer"}, "encoding": {"type": "string"}},
            ["path"],
        ),
        _tool(
            "write_file",
            "Write or append a local text file.",
            {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "append": {"type": "boolean"},
                "create_dirs": {"type": "boolean"},
                "encoding": {"type": "string"},
            },
            ["path", "content"],
        ),
        _tool(
            "run_command",
            "Run a local command and return stdout, stderr, and exit code. Default shell is powershell; set shell for cmd/bash/sh when needed.",
            {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
                "timeout_seconds": {"type": "integer"},
                "shell": {"type": "string", "enum": ["powershell", "pwsh", "cmd", "bash", "sh"]},
            },
            ["command"],
        ),
    ]


def _tool(name: str, description: str, properties: dict[str, dict[str, Any]], required: list[str] | None = None) -> dict[str, Any]:
    parameters: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        parameters["required"] = required
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


def _numeric_value_schema() -> dict[str, Any]:
    return {"anyOf": [{"type": "integer"}, {"type": "number"}, {"type": "string"}]}


def _byte_sequence_schema() -> dict[str, Any]:
    return {
        "anyOf": [
            {"type": "string"},
            {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 255}},
        ]
    }


def _action_from_tool_call(name: str, arguments: dict[str, Any]) -> AgentAction:
    try:
        action_type = ActionType(name)
    except ValueError:
        action_type = ActionType.UNSUPPORTED
        arguments = {"category": "unknown_tool", "tool_name": name, "arguments": arguments}
    return AgentAction(type=action_type, arguments=arguments, reason="LLM tool call")


def _parse_tool_arguments(raw_args: Any) -> tuple[dict[str, Any], str | None]:
    if raw_args in (None, ""):
        return {}, None
    if isinstance(raw_args, dict):
        return dict(raw_args), None
    if not isinstance(raw_args, str):
        return {}, f"arguments must be a JSON object string, got {type(raw_args).__name__}"
    try:
        parsed = json.loads(raw_args)
    except json.JSONDecodeError as exc:
        return {}, f"invalid JSON: {exc.msg} at char {exc.pos}"
    if not isinstance(parsed, dict):
        return {}, f"arguments must decode to a JSON object, got {type(parsed).__name__}"
    return parsed, None


def _assistant_message_from_response(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise RuntimeError(f"LLM 返回格式无效：期望 object，实际 {type(response).__name__}")
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("LLM 返回格式无效：缺少 choices[0].message")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise RuntimeError(f"LLM 返回格式无效：choices[0] 应为 object，实际 {type(first_choice).__name__}")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise RuntimeError("LLM 返回格式无效：缺少 choices[0].message")
    return dict(message)


def _normalize_tool_calls(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    if isinstance(value, dict) and ("tool_calls" in value or "function_call" in value):
        calls = _normalize_tool_calls(value.get("tool_calls"))
        if calls:
            return calls
        function_call = value.get("function_call")
        if isinstance(function_call, dict) and function_call.get("name"):
            return [
                {
                    "id": "legacy_function_call",
                    "type": "function",
                    "function": {
                        "name": function_call.get("name"),
                        "arguments": function_call.get("arguments") or "{}",
                    },
                }
            ]
        return []
    if isinstance(value, dict):
        if not isinstance(value.get("function"), dict):
            return []
        call = dict(value)
        if not call.get("id"):
            call["id"] = "tool_call_1"
        return [call]
    if isinstance(value, list):
        calls: list[dict[str, Any]] = []
        for index, item in enumerate(value):
            for call in _normalize_tool_calls(item):
                if call.get("id") == "tool_call_1":
                    call["id"] = f"tool_call_{index + 1}"
                calls.append(call)
        return calls
    return []


def _normalize_assistant_message(message: dict[str, Any]) -> dict[str, Any]:
    if message.get("tool_calls") or not isinstance(message.get("function_call"), dict):
        return message
    tool_calls = _normalize_tool_calls({"function_call": message.get("function_call")})
    if not tool_calls:
        return message
    normalized = dict(message)
    normalized["tool_calls"] = tool_calls
    normalized.pop("function_call", None)
    return normalized


def _fallback_assistant_message(results: list[ActionResult], exc: Exception) -> str:
    last = results[-1]
    lines = [last.message]
    next_step = _find_next_step_in_result(last)
    if next_step:
        lines.append(f"下一步：{next_step}")
    lines.append(f"注：工具结果已返回，但最终 LLM 总结失败：{exc}")
    return "\n".join(lines)


def _find_next_step_in_result(result: ActionResult) -> str | None:
    next_step = result.data.get("next_step")
    if next_step:
        return str(next_step)
    followup = result.data.get("followup")
    if isinstance(followup, dict):
        write = followup.get("write")
        if isinstance(write, dict) and write.get("error"):
            return str(write["error"])
    return None


def result_to_tool_payload(result: ActionResult) -> dict[str, Any]:
    payload = {
        "action": {
            "type": result.action.type.value,
            "arguments": _compact_for_tool_observation(result.action.arguments),
            "reason": result.action.reason,
        },
        "ok": result.ok,
        "message": result.message,
        "data": _compact_for_tool_observation(result.data),
    }
    return _fit_tool_payload(payload)


_TOOL_OBSERVATION_MAX_CHARS = int(os.getenv("CHEATPILOT_TOOL_OBSERVATION_MAX_CHARS", "24000"))
_TOOL_OBSERVATION_STRING_CHARS = int(os.getenv("CHEATPILOT_TOOL_OBSERVATION_STRING_CHARS", "4000"))
_TOOL_OBSERVATION_ITEMS = int(os.getenv("CHEATPILOT_TOOL_OBSERVATION_ITEMS", "80"))
_TOOL_OBSERVATION_DEPTH = int(os.getenv("CHEATPILOT_TOOL_OBSERVATION_DEPTH", "6"))


def _compact_for_tool_observation(value: Any, *, depth: int = 0) -> Any:
    if depth >= _TOOL_OBSERVATION_DEPTH:
        return _summarize_value(value)
    if isinstance(value, str):
        return _truncate_text(value, _TOOL_OBSERVATION_STRING_CHARS)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        items = [_compact_for_tool_observation(item, depth=depth + 1) for item in value[:_TOOL_OBSERVATION_ITEMS]]
        if len(value) > _TOOL_OBSERVATION_ITEMS:
            items.append({"truncated_items": len(value) - _TOOL_OBSERVATION_ITEMS})
        return items
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        items = list(value.items())
        for key, item in items[:_TOOL_OBSERVATION_ITEMS]:
            output[str(key)] = _compact_for_tool_observation(item, depth=depth + 1)
        if len(items) > _TOOL_OBSERVATION_ITEMS:
            output["truncated_items"] = len(items) - _TOOL_OBSERVATION_ITEMS
        return output
    return _summarize_value(value)


def _fit_tool_payload(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, ensure_ascii=False, default=str)
    if len(encoded) <= _TOOL_OBSERVATION_MAX_CHARS:
        return payload
    return {
        "action": payload.get("action"),
        "ok": payload.get("ok"),
        "message": payload.get("message"),
        "data": _summarize_value(payload.get("data")),
        "truncated_for_llm": True,
        "original_chars": len(encoded),
    }


def _truncate_text(value: str, max_chars: int) -> str | dict[str, Any]:
    if len(value) <= max_chars:
        return value
    return {
        "preview": value[:max_chars],
        "truncated": True,
        "original_chars": len(value),
    }


def _summarize_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {"type": "object", "keys": list(value.keys())[:_TOOL_OBSERVATION_ITEMS], "size": len(value)}
    if isinstance(value, list):
        return {"type": "array", "size": len(value)}
    if isinstance(value, str):
        return {"type": "string", "preview": value[:240], "original_chars": len(value)}
    return {"type": type(value).__name__, "repr": str(value)[:240]}


def _append_skipped_tool_results(messages: list[dict[str, Any]], tool_calls: list[dict[str, Any]]) -> None:
    for tool_call in tool_calls:
        function = tool_call.get("function") or {}
        name = str(function.get("name") or "unknown")
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.get("id"),
                "name": name,
                "content": json.dumps(
                    {
                        "ok": False,
                        "message": "Skipped because a previous required tool failed and the plan was stopped.",
                        "data": {"skipped": True},
                    },
                    ensure_ascii=False,
                ),
            }
        )


def _is_retryable_http_error(exc: urllib.error.HTTPError) -> bool:
    return exc.code in {408, 409, 425, 429, 500, 502, 503, 504}


def _retry_delay_seconds(attempt: int, exc: urllib.error.HTTPError | None = None) -> float:
    if exc is not None:
        retry_after = exc.headers.get("Retry-After")
        if retry_after:
            try:
                return min(max(float(retry_after), 1.0), 60.0)
            except ValueError:
                pass
        if exc.code == 429:
            return min(5.0 * (2.0**attempt), 60.0)
    return min(2.0**attempt, 15.0)
