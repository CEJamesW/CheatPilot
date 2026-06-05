from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

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
    max_tool_rounds: int = 6
    max_history_messages: int = 12
    _conversation: list[dict[str, str]] = field(default_factory=list, init=False, repr=False)

    def handle(self, message: str) -> AgentResponse:
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
            response = self._chat(messages, tools=tool_schemas())
            choice = dict(response["choices"][0]["message"])
            messages.append(choice)
            tool_calls = choice.get("tool_calls") or []
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
                raw_args = str(function.get("arguments") or "{}")
                try:
                    arguments = json.loads(raw_args)
                except json.JSONDecodeError:
                    arguments = {}
                action = _action_from_tool_call(name, arguments)
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
            assistant_message = self._finalize_from_tool_results(messages)

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
                    return dict(json.loads(response.read().decode("utf-8")))
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
                    "不要再调用工具；如工具结果要求用户继续改变数值，就明确告诉用户下一步要做什么。"
                ),
            },
        ]
        response = self._chat(final_messages)
        choice = dict(response["choices"][0]["message"])
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
            "You are the only planner in this product: every user message reaches you first. "
            "Use tools to inspect and modify memory through Cheat Engine MCP when the user asks for memory work. "
            "Reply in Chinese unless the user asks otherwise. "
            "Treat words such as hook, attach, connect, 打开, 连接, 附加到, and hook住 as requests to call attach_process when a target process or game is named. "
            "For a numeric value change request, call attach_process when a process is named, "
            "then scan_exact_value with the current value, then write_value with the desired value, "
            "and print_base_address when the user asks for address/base address. "
            "Use process PlantsVsZombies when the user says PVZ or 植物大战僵尸. "
            "If scan results are not unique, tell the user to change the value in the target program and report the new value; "
            "when they report the new value, call next_scan using the saved label. "
            "For reset/status requests, call reset_session/session_status instead of answering from memory. "
            "For string replacement, call scan_string, write_string, then read_string when verification is useful. "
            "For explicit byte patches, call write_bytes only when the user provides an explicit address and byte sequence. "
            "For casual chat or help, answer normally without tools. "
            "Do not claim success unless a tool result confirms it."
        )


def tool_schemas() -> list[dict[str, Any]]:
    return [
        _tool("attach_process", "Attach Cheat Engine to a process.", {"process": {"type": "string"}}, ["process"]),
        _tool("get_process_info", "Get attached process information.", {}),
        _tool("session_status", "Show saved scan session status.", {"label": {"type": "string"}}),
        _tool("reset_session", "Clear saved CheatPilot scan session.", {}),
        _tool(
            "scan_exact_value",
            "Scan for an exact numeric value.",
            {"label": {"type": "string"}, "value": {"type": "integer"}, "value_type": {"type": "string"}},
            ["label", "value"],
        ),
        _tool(
            "next_scan",
            "Filter previous scan by a new value.",
            {"label": {"type": "string"}, "value": {"type": "integer"}, "scan_type": {"type": "string"}},
            ["label", "value"],
        ),
        _tool(
            "write_value",
            "Write a numeric value to a unique known address or explicit address.",
            {"label": {"type": "string"}, "value": {"type": "integer"}, "address": {"type": "string"}, "value_type": {"type": "string"}},
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
            {"address": {"type": "string"}, "bytes": {"type": "string"}},
            ["address", "bytes"],
        ),
        _tool(
            "evaluate_lua",
            "Execute benign Cheat Engine Lua automation if enabled by configuration.",
            {"code": {"type": "string"}},
            ["code"],
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


def _action_from_tool_call(name: str, arguments: dict[str, Any]) -> AgentAction:
    try:
        action_type = ActionType(name)
    except ValueError:
        action_type = ActionType.UNSUPPORTED
        arguments = {"category": "unknown_tool", "tool_name": name, "arguments": arguments}
    return AgentAction(type=action_type, arguments=arguments, reason="LLM tool call")


def result_to_tool_payload(result: ActionResult) -> dict[str, Any]:
    return {
        "action": {
            "type": result.action.type.value,
            "arguments": result.action.arguments,
            "reason": result.action.reason,
        },
        "ok": result.ok,
        "message": result.message,
        "data": result.data,
    }


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
