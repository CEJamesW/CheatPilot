from __future__ import annotations

from typing import Any

from cheatpilot.models import AgentResponse


def format_response(response: AgentResponse, *, include_json_hint: bool = False) -> str:
    """Build a compact user-facing summary for CLI, API, and desktop UI."""

    if response.assistant_message:
        lines = [response.assistant_message]
        if include_json_hint:
            lines.append("需要完整机器结果时可在 CLI 使用 --json，或调用 API 的 /chat 返回结构化字段。")
        return "\n".join(lines)

    lines: list[str] = []
    for index, result in enumerate(response.results, start=1):
        status = "完成" if result.ok else "失败"
        lines.append(f"{index}. [{status}] {result.message}")
        next_step = _find_next_step(result.data)
        if next_step:
            lines.append(f"下一步：{next_step}")

    final = _final_summary(response)
    if final:
        lines.append(final)

    if include_json_hint:
        lines.append("需要完整机器结果时可在 CLI 使用 --json，或调用 API 的 /chat 返回结构化字段。")
    return "\n".join(lines)


def _final_summary(response: AgentResponse) -> str | None:
    for result in reversed(response.results):
        followup = result.data.get("followup")
        if isinstance(followup, dict):
            write = followup.get("write")
            base_address = followup.get("base_address")
            if isinstance(write, dict) and base_address:
                label = write.get("label") or "value"
                value = write.get("value")
                address = write.get("address")
                readback = _extract_readback_value(write.get("readback"))
                tail = f"，读回值 {readback}" if readback is not None else ""
                return f"结果：{label} 已写入 {value}，地址/基址 {address or base_address}{tail}。"
        address = result.data.get("address")
        value = result.data.get("value")
        label = result.data.get("label")
        if address and value is not None and result.action.type.value == "write_value":
            readback = _extract_readback_value(result.data.get("readback"))
            tail = f"，读回值 {readback}" if readback is not None else ""
            return f"结果：{label or 'value'} 已写入 {value}，地址 {address}{tail}。"
    return None


def _find_next_step(data: dict[str, Any]) -> str | None:
    next_step = data.get("next_step")
    return str(next_step) if next_step else None


def _extract_readback_value(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("value", "result", "data"):
            if key in value and not isinstance(value[key], (dict, list)):
                return value[key]
        for nested in value.values():
            extracted = _extract_readback_value(nested)
            if extracted is not None:
                return extracted
    if isinstance(value, list):
        for item in value:
            extracted = _extract_readback_value(item)
            if extracted is not None:
                return extracted
    return None
