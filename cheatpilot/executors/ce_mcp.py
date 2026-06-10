from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cheatpilot.config import DEFAULT_MCP_ARGS, DEFAULT_MCP_COMMAND, PROJECT_ROOT
from cheatpilot.mcp_client import MCPError, MCPStdioClient
from cheatpilot.models import ActionResult, ActionType, AgentAction


@dataclass
class CheatEngineMCPExecutor:
    """Executor that maps CheatPilot actions to Cheat Engine MCP tools."""

    command: str = DEFAULT_MCP_COMMAND
    args: list[str] = field(default_factory=lambda: list(DEFAULT_MCP_ARGS))
    value_type: str = "dword"
    protection: str = "+W-C"
    max_scan_results: int = 25
    allow_lua_actions: bool = False
    timeout_seconds: float = 60.0
    state_path: Path = field(default_factory=lambda: PROJECT_ROOT / "runtime" / "session_state.json")
    _client: MCPStdioClient | None = field(default=None, init=False, repr=False)
    _last_scan_by_label: dict[str, list[str]] = field(default_factory=dict, init=False)
    _last_string_wide_by_label: dict[str, bool] = field(default_factory=dict, init=False)
    _state: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self._state = self._load_state()
        self._migrate_state_labels()

    def execute(self, action: AgentAction) -> ActionResult:
        try:
            return self._execute(action)
        except (MCPError, OSError, RuntimeError, ValueError, KeyError) as exc:
            message = _friendly_error(str(exc))
            return ActionResult(
                action=action,
                ok=False,
                message=f"Cheat Engine MCP error: {message}",
                data={"error": str(exc)},
            )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _execute(self, action: AgentAction) -> ActionResult:
        if action.type == ActionType.ATTACH_PROCESS:
            return self._attach_process(action)
        if action.type == ActionType.GET_PROCESS_INFO:
            return self._get_process_info(action)
        if action.type == ActionType.SESSION_STATUS:
            return self._session_status(action)
        if action.type == ActionType.RESET_SESSION:
            return self._reset_session(action)
        if action.type == ActionType.SCAN_EXACT_VALUE:
            return self._scan_exact_value(action)
        if action.type == ActionType.NEXT_SCAN:
            return self._next_scan(action)
        if action.type == ActionType.WRITE_VALUE:
            return self._write_value(action)
        if action.type == ActionType.PRINT_BASE_ADDRESS:
            return self._print_base_address(action)
        if action.type == ActionType.READ_VALUE:
            return self._read_value(action)
        if action.type == ActionType.SCAN_STRING:
            return self._scan_string(action)
        if action.type == ActionType.READ_STRING:
            return self._read_string(action)
        if action.type == ActionType.SCAN_AOB:
            return self._aob_scan(action)
        if action.type == ActionType.WRITE_BYTES:
            return self._write_bytes(action)
        if action.type == ActionType.WRITE_STRING:
            return self._write_string(action)
        if action.type == ActionType.EVALUATE_LUA:
            return self._evaluate_lua(action)
        if action.type == ActionType.LIST_CE_TOOLS:
            return self._list_ce_tools(action)
        if action.type == ActionType.CE_MCP_CALL:
            return self._ce_mcp_call(action)
        if action.type == ActionType.EXPLAIN:
            return ActionResult(action=action, ok=True, message=str(action.arguments.get("text", "")), data={})
        if action.type == ActionType.UNSUPPORTED:
            return ActionResult(
                action=action,
                ok=False,
                message=f"Unsupported operation: {action.arguments.get('category', 'unknown')}",
                data=dict(action.arguments),
            )
        return ActionResult(action=action, ok=False, message=f"Unhandled action: {action.type}", data={})

    def _attach_process(self, action: AgentAction) -> ActionResult:
        pid = _optional_int(action.arguments.get("pid") or action.arguments.get("process_id"))
        process = str(action.arguments.get("process") or action.arguments.get("name") or "").strip()
        if pid is None and not process:
            raise ValueError("attach_process requires a process or pid argument")
        if pid is not None:
            result = self._call("evaluate_lua", {"code": f"openProcess({pid})\nreturn getOpenedProcessID()"})
        else:
            escaped = process.replace("\\", "\\\\").replace('"', '\\"')
            result = self._call("evaluate_lua", {"code": f'openProcess("{escaped}")\nreturn getOpenedProcessID()'})
        process_info = self._call("get_process_info", {})
        verified = _process_matches(process, process_info) if pid is None else _process_id_matches(pid, process_info)
        target = str(pid) if pid is not None else process
        if not verified:
            return ActionResult(
                action=action,
                ok=False,
                message=(
                    f"未能确认 Cheat Engine 已附加到目标进程 '{target}'。"
                    "为避免在错误进程上扫描/写入，已停止本次计划。"
                ),
                data={
                    "process": process,
                    "pid": pid,
                    "result": result,
                    "process_info": process_info,
                    "fatal": True,
                    "next_step": f"请确认目标进程正在运行，并使用 list_processes 找到准确进程名或 PID 后再附加。",
                },
            )
        self._state["process"] = process or target
        if pid is not None:
            self._state["pid"] = pid
        self._save_state()
        return ActionResult(
            action=action,
            ok=True,
            message=f"已通过 Cheat Engine MCP 附加到进程 '{process or target}'。",
            data={"process": process or None, "pid": pid, "result": result, "process_info": process_info},
        )

    def _get_process_info(self, action: AgentAction) -> ActionResult:
        result = self._call("get_process_info", {})
        ok = not (isinstance(result, dict) and result.get("success") is False)
        return ActionResult(
            action=action,
            ok=ok,
            message=_brief_result("Process info", result),
            data={"result": result},
        )

    def _session_status(self, action: AgentAction) -> ActionResult:
        raw_label = str(action.arguments.get("label") or "")
        ambiguous = []
        label = ""
        if raw_label:
            label, ambiguous = self._label_from_action(action, default="", infer=True)
        if ambiguous:
            return self._ambiguous_label_result(action, ambiguous)
        selected = self._get_existing_label_state(label) if label else None
        labels = dict(self._state.get("labels") or {})
        pending_count = sum(
            1
            for state in labels.values()
            if isinstance(state, dict) and (state.get("pending_write") or state.get("pending_base"))
        )

        if selected:
            addresses = list(selected.get("addresses") or [])
            total = selected.get("total")
            last_value = selected.get("last_value")
            pending_write = selected.get("pending_write")
            pending_base = bool(selected.get("pending_base"))
            message = (
                f"{label} 会话状态：上次值 {last_value}，当前候选 {len(addresses)} 个可见"
                f"，CE 总数 {total if total is not None else '未知'}。"
            )
            if pending_write:
                message += f" 待写入 {pending_write.get('value')}。"
            if pending_base:
                message += " 待打印基址。"
            if not _is_unique_candidate(addresses, total):
                message += f" 下一步：让 {label} 在目标进程里再变化一次，然后告诉我新的数值。"
        elif labels:
            message = f"当前保存了 {len(labels)} 个标签的扫描会话，{pending_count} 个有待执行后续动作。"
        else:
            message = "当前没有保存的扫描会话。"

        return ActionResult(
            action=action,
            ok=True,
            message=message,
            data={"label": label or None, "process": self._state.get("process"), "labels": labels},
        )

    def _reset_session(self, action: AgentAction) -> ActionResult:
        previous_labels = list((self._state.get("labels") or {}).keys())
        self._state = {}
        self._last_scan_by_label.clear()
        self._last_string_wide_by_label.clear()
        self._save_state()
        return ActionResult(
            action=action,
            ok=True,
            message="已清空 CheatPilot 保存的扫描会话。下一条修改请求会从新的 scan_all 开始。",
            data={"cleared_labels": previous_labels},
        )

    def _scan_exact_value(self, action: AgentAction) -> ActionResult:
        label = self._label_from_action(action, infer=False)[0]
        value = str(action.arguments["value"])
        value_type = str(action.arguments.get("value_type") or self.value_type)
        self._clear_label_followups(label)
        result = self._call("scan_all", {"value": value, "type": value_type, "protection": self.protection})
        addresses = _extract_addresses(result)
        if not addresses:
            extra = self._try_get_scan_results()
            addresses = _extract_addresses(extra)
            result = {"scan": result, "results": extra}
        total = _extract_total_count(result)
        self._remember_scan(label, addresses, total, value, value_type)
        message = f"已扫描 {label}={value}，当前返回 {len(addresses)} 个候选地址。"
        if total and total > len(addresses):
            message += f" Cheat Engine 总匹配数为 {total}。"
        if total and total > 1:
            message += f" 请让 {label} 在目标进程里变化一次，然后告诉我新的数值，我会继续 next_scan。"
        next_step = _next_step_for_candidates(label, total, len(addresses))
        return ActionResult(
            action=action,
            ok=bool(addresses) or not _is_error_result(result),
            message=message,
            data={
                "label": label,
                "value": value,
                "value_type": value_type,
                "addresses": addresses,
                "total": total,
                "next_step": next_step,
                "raw": result,
            },
        )

    def _next_scan(self, action: AgentAction) -> ActionResult:
        label, ambiguous = self._label_from_action(action, infer=True)
        if ambiguous:
            return self._ambiguous_label_result(action, ambiguous)
        value = str(action.arguments.get("value", ""))
        scan_type = str(action.arguments.get("scan_type") or "exact")
        known_addresses, known_total = self._candidate_info(label)
        if not known_addresses and known_total is None:
            first_scan_action = AgentAction(
                type=ActionType.SCAN_EXACT_VALUE,
                arguments={"label": label, "value": value},
                reason="No saved scan exists; treating the reported value as a first exact scan.",
            )
            result = self._scan_exact_value(first_scan_action)
            result.message = (
                f"还没有 {label} 的上一轮扫描；我已把 {label}={value} 当作首次扫描。"
                f" {result.message}"
            )
            result.data["converted_from_next_scan"] = True
            return result

        result = self._call("next_scan", {"value": value, "scan_type": scan_type})
        addresses = _extract_addresses(result)
        if not addresses:
            extra = self._try_get_scan_results()
            addresses = _extract_addresses(extra)
            result = {"next_scan": result, "results": extra}
        total = _extract_total_count(result)
        value_type = str(self._label_state(label).get("value_type") or self.value_type)
        self._remember_scan(label, addresses, total, value, value_type)
        message = f"已执行 next_scan({scan_type})，当前返回 {len(addresses)} 个候选地址。"
        if total and total > len(addresses):
            message += f" Cheat Engine 总匹配数为 {total}。"
        if total and total > 1:
            message += f" 请让 {label} 再变化一次，然后告诉我新的数值。"
        followup_data = self._run_pending_followups(label, addresses, total)
        if followup_data:
            if followup_data.get("write"):
                write = followup_data["write"]
                if write.get("ok"):
                    message += f" 已将待写入的 {label}={write['value']} 写到 {write['address']}。"
                else:
                    message += f" 待写入 {label}={write['value']} 未确认成功：{write.get('error', '写入或读回失败')}。"
            if followup_data.get("base_address"):
                message += f" {label} 基址：{followup_data['base_address']}。"
        next_step = _next_step_for_candidates(label, total, len(addresses))
        ok = not _is_error_result(result) and _followups_ok(followup_data)
        return ActionResult(
            action=action,
            ok=ok,
            message=message,
            data={
                "label": label,
                "value": value,
                "value_type": value_type,
                "scan_type": scan_type,
                "addresses": addresses,
                "total": total,
                "next_step": next_step,
                "raw": result,
                "followup": followup_data,
            },
        )

    def _write_value(self, action: AgentAction) -> ActionResult:
        value_type = str(action.arguments.get("value_type") or self.value_type)
        value = _coerce_numeric_value(action.arguments["value"], value_type)
        explicit_address = action.arguments.get("address")
        if explicit_address:
            label = _canonical_label(action.arguments.get("label") or "value")
            address = str(explicit_address)
        else:
            label, ambiguous = self._label_from_action(action, infer=True)
            if ambiguous:
                return self._ambiguous_label_result(action, ambiguous)
            addresses, total = self._candidate_info(label)
            if not addresses:
                self._remember_pending_write(label, value, value_type)
                return ActionResult(
                    action=action,
                    ok=False,
                    message=f"尚未找到 {label} 的地址；已保存待写入 {label}={value}，请先提供当前值开始扫描。",
                    data={
                        "label": label,
                        "value": value,
                        "value_type": value_type,
                        "deferred": True,
                        "next_step": f"告诉我当前{label}是多少，例如：现在{label}是100。",
                    },
                )
            if not _is_unique_candidate(addresses, total):
                self._remember_pending_write(label, value, value_type)
                return ActionResult(
                    action=action,
                    ok=True,
                    message=(
                        f"已暂存写入 {label}={value}：当前 {len(addresses)} 个可见候选，"
                        f"CE 总数 {total if total is not None else '未知'}。请让 {label} 变化后告诉我新值。"
                    ),
                    data={
                        "label": label,
                        "value": value,
                        "value_type": value_type,
                        "addresses": addresses,
                        "total": total,
                        "deferred": True,
                        "next_step": _next_step_for_candidates(label, total, len(addresses)),
                    },
                )
            address = addresses[0]
        result = self._call("write_integer", {"address": address, "value": value, "type": value_type})
        readback = self._call("read_integer", {"address": address, "type": value_type})
        write_ok = _write_confirmed(result, readback, value)
        if write_ok:
            message = f"已通过 Cheat Engine MCP 将 {label}={value} 写入 {address}。"
        else:
            message = f"Cheat Engine MCP 已返回写入结果，但未确认 {label}={value} 已成功写入 {address}。"
        return ActionResult(
            action=action,
            ok=write_ok,
            message=message,
            data={
                "label": label,
                "address": address,
                "value": value,
                "value_type": value_type,
                "raw": result,
                "readback": readback,
                "confirmed": write_ok,
            },
        )

    def _print_base_address(self, action: AgentAction) -> ActionResult:
        label, ambiguous = self._label_from_action(action, infer=True)
        if ambiguous:
            return self._ambiguous_label_result(action, ambiguous)
        addresses, total = self._candidate_info(label)
        address = addresses[0] if _is_unique_candidate(addresses, total) else None
        if not address:
            self._remember_pending_base(label)
        return ActionResult(
            action=action,
            ok=True,
            message=(
                f"{label} 基址：{address}"
                if address
                else f"{label} 还没有唯一地址；已暂存打印基址请求，等 next_scan 缩到唯一后自动打印。"
            ),
            data={
                "label": label,
                "base_address": address,
                "deferred": address is None,
                "next_step": None if address else _next_step_for_candidates(label, total, len(addresses)),
            },
        )

    def _read_value(self, action: AgentAction) -> ActionResult:
        explicit_address = action.arguments.get("address")
        if explicit_address:
            label = _canonical_label(action.arguments.get("label") or "value")
        else:
            label, ambiguous = self._label_from_action(action, infer=True)
            if ambiguous:
                return self._ambiguous_label_result(action, ambiguous)
        address = self._resolve_address(action, label)
        value_type = str(action.arguments.get("value_type") or self.value_type)
        result = self._call("read_integer", {"address": address, "type": value_type})
        return ActionResult(
            action=action,
            ok=not _is_error_result(result),
            message=f"已从 {address} 读取 {label}。",
            data={"label": label, "address": address, "value_type": value_type, "raw": result},
        )

    def _scan_string(self, action: AgentAction) -> ActionResult:
        label = _canonical_label(action.arguments.get("label") or "string")
        value = str(action.arguments["value"])
        wide = bool(action.arguments.get("wide", False))
        limit = int(action.arguments.get("limit") or self.max_scan_results)
        try:
            result = self._call("search_string", {"string": value, "wide": wide, "limit": limit})
        except MCPError:
            result = self._call("scan_all", {"value": value, "type": "string", "protection": self.protection})
        addresses = _extract_addresses(result)
        if not addresses and not wide:
            wide = True
            result = self._call("search_string", {"string": value, "wide": wide, "limit": limit})
            addresses = _extract_addresses(result)
        self._last_scan_by_label[label] = addresses
        self._last_string_wide_by_label[label] = wide
        return ActionResult(
            action=action,
            ok=bool(addresses) or not _is_error_result(result),
            message=f"Scanned string {label!r}; found {len(addresses)} candidate address(es).",
            data={"label": label, "value": value, "wide": wide, "addresses": addresses, "raw": result},
        )

    def _read_string(self, action: AgentAction) -> ActionResult:
        label = _canonical_label(action.arguments.get("label") or "string")
        address = self._resolve_address(action, label)
        max_length = int(action.arguments.get("max_length") or 256)
        wide = self._last_string_wide_by_label.get(label, bool(action.arguments.get("wide", False)))
        ce_max_length = max_length * 2 if wide else max_length
        result = self._call("read_string", {"address": address, "max_length": ce_max_length, "wide": wide})
        return ActionResult(
            action=action,
            ok=not _is_error_result(result),
            message=f"Read string from {address}.",
            data={
                "label": label,
                "address": address,
                "max_length": max_length,
                "ce_max_length": ce_max_length,
                "wide": wide,
                "raw": result,
            },
        )

    def _aob_scan(self, action: AgentAction) -> ActionResult:
        pattern = str(action.arguments["pattern"])
        limit = int(action.arguments.get("limit") or self.max_scan_results)
        protection = str(action.arguments.get("protection") or "+X")
        result = self._call("aob_scan", {"pattern": pattern, "protection": protection, "limit": limit})
        addresses = _extract_addresses(result)
        return ActionResult(
            action=action,
            ok=not _is_error_result(result),
            message=f"AOB scan found {len(addresses)} candidate address(es).",
            data={"pattern": pattern, "addresses": addresses, "raw": result},
        )

    def _write_bytes(self, action: AgentAction) -> ActionResult:
        address = str(action.arguments["address"])
        bytes_value = action.arguments["bytes"]
        if isinstance(bytes_value, str):
            bytes_list = [int(part, 16) for part in bytes_value.replace(",", " ").split()]
        else:
            bytes_list = [int(item) for item in bytes_value]
        result = self._call("write_memory", {"address": address, "bytes": bytes_list})
        return ActionResult(
            action=action,
            ok=not _is_error_result(result),
            message=f"Wrote {len(bytes_list)} byte(s) to {address}.",
            data={"address": address, "bytes": bytes_list, "raw": result},
        )

    def _write_string(self, action: AgentAction) -> ActionResult:
        label = _canonical_label(action.arguments.get("label") or "string")
        address = self._resolve_address(action, label)
        value = str(action.arguments["value"])
        wide = self._last_string_wide_by_label.get(label, bool(action.arguments.get("wide", False)))
        result = self._call("write_string", {"address": address, "value": value, "wide": wide})
        return ActionResult(
            action=action,
            ok=not _is_error_result(result),
            message=f"Wrote string to {address}.",
            data={"label": label, "address": address, "value": value, "wide": wide, "raw": result},
        )

    def _evaluate_lua(self, action: AgentAction) -> ActionResult:
        if not self.allow_lua_actions:
            return ActionResult(
                action=action,
                ok=False,
                message="Lua actions are disabled by default. Set CHEATPILOT_ALLOW_LUA=1 to enable them.",
                data={"enabled": False},
            )
        code = str(action.arguments["code"])
        result = self._call("evaluate_lua", {"code": code})
        return ActionResult(
            action=action,
            ok=not _is_error_result(result),
            message="Executed Lua through Cheat Engine MCP.",
            data={"raw": result},
        )

    def _list_ce_tools(self, action: AgentAction) -> ActionResult:
        tools = self._get_client().list_tools()
        limit = int(action.arguments.get("limit") or 80)
        query = str(action.arguments.get("query") or "").strip().lower()
        items: list[dict[str, Any]] = []
        for tool in tools:
            haystack = f"{tool.name} {tool.description}".lower()
            if query and query not in haystack:
                continue
            items.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
            )
            if len(items) >= limit:
                break
        return ActionResult(
            action=action,
            ok=True,
            message=f"已列出 {len(items)} 个 Cheat Engine MCP 工具。",
            data={"query": query or None, "tools": items, "total_available": len(tools)},
        )

    def _ce_mcp_call(self, action: AgentAction) -> ActionResult:
        tool_name = str(action.arguments.get("tool_name") or action.arguments.get("name") or "")
        if not tool_name:
            raise ValueError("ce_mcp_call requires tool_name")
        arguments = action.arguments.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError("ce_mcp_call arguments must be an object")
        result = self._call(tool_name, arguments)
        return ActionResult(
            action=action,
            ok=not _is_error_result(result),
            message=f"已调用 Cheat Engine MCP 工具 {tool_name}。",
            data={"tool_name": tool_name, "arguments": arguments, "raw": result},
        )

    def _resolve_address(self, action: AgentAction, label: str, required: bool = True) -> str | None:
        label = _canonical_label(label)
        explicit = action.arguments.get("address")
        if explicit:
            return str(explicit)
        addresses, total = self._candidate_info(label)
        if addresses:
            if required and not _is_unique_candidate(addresses, total):
                raise ValueError(f"{label} has {len(addresses)} visible candidates and {total} total; narrow with next_scan first")
            return addresses[0]
        if required:
            raise ValueError(f"no known address for {label}; scan first or pass address explicitly")
        return None

    def _candidate_info(self, label: str) -> tuple[list[str], int | None]:
        label = _canonical_label(label)
        state = self._label_state(label)
        addresses = self._last_scan_by_label.get(label) or list(state.get("addresses") or [])
        total = state.get("total")
        if not _state_has_known_total(state, total, len(addresses)):
            total = None
        return addresses, total

    def _remember_scan(
        self,
        label: str,
        addresses: list[str],
        total: int | None,
        value: str,
        value_type: str,
    ) -> None:
        label = _canonical_label(label)
        self._last_scan_by_label[label] = addresses
        state = self._label_state(label)
        state.update(
            {
                "addresses": addresses,
                "total": total,
                "total_known": total is not None,
                "last_value": value,
                "value_type": value_type,
            }
        )
        self._save_state()

    def _remember_pending_write(self, label: str, value: int, value_type: str) -> None:
        label = _canonical_label(label)
        state = self._label_state(label)
        state["pending_write"] = {"value": value, "value_type": value_type}
        self._save_state()

    def _remember_pending_base(self, label: str) -> None:
        label = _canonical_label(label)
        state = self._label_state(label)
        state["pending_base"] = True
        self._save_state()

    def _clear_label_followups(self, label: str) -> None:
        label = _canonical_label(label)
        state = self._label_state(label)
        changed = False
        for key in ("pending_write", "pending_base", "final_address", "completed"):
            if key in state:
                state.pop(key, None)
                changed = True
        if changed:
            self._save_state()

    def _run_pending_followups(self, label: str, addresses: list[str], total: int | None) -> dict[str, Any]:
        label = _canonical_label(label)
        if not _is_unique_candidate(addresses, total):
            return {}

        state = self._label_state(label)
        address = addresses[0]
        followup: dict[str, Any] = {}
        pending_write = state.get("pending_write")
        if isinstance(pending_write, dict):
            value_type = str(pending_write.get("value_type") or self.value_type)
            value = _coerce_numeric_value(pending_write["value"], value_type)
            raw = self._call("write_integer", {"address": address, "value": value, "type": value_type})
            readback = self._call("read_integer", {"address": address, "type": value_type})
            ok = _write_confirmed(raw, readback, value)
            followup["write"] = {
                "label": label,
                "address": address,
                "value": value,
                "value_type": value_type,
                "ok": ok,
                "raw": raw,
                "readback": readback,
                "error": None if ok else _write_error_message(raw, readback, value),
            }
            if ok:
                state.pop("pending_write", None)

        if state.get("pending_base"):
            followup["base_address"] = address
            state.pop("pending_base", None)

        if followup:
            state["final_address"] = address
            if _followups_ok(followup):
                state["completed"] = True
            self._save_state()
        return followup

    def _label_state(self, label: str) -> dict[str, Any]:
        label = _canonical_label(label)
        self._merge_label_aliases(label)
        labels = self._state.setdefault("labels", {})
        return labels.setdefault(label, {})

    def _get_existing_label_state(self, label: str) -> dict[str, Any] | None:
        label = _canonical_label(label)
        self._merge_label_aliases(label)
        labels = self._state.setdefault("labels", {})
        state = labels.get(label)
        return state if isinstance(state, dict) else None

    def _label_from_action(self, action: AgentAction, default: str = "value", infer: bool = False) -> tuple[str, list[str]]:
        requested = _canonical_label(action.arguments.get("label") or default)
        if infer and _is_placeholder_label(requested):
            active_labels = self._active_labels()
            if len(active_labels) == 1:
                return active_labels[0], []
            if len(active_labels) > 1:
                return requested, active_labels
        return requested, []

    def _active_labels(self) -> list[str]:
        self._migrate_state_labels()
        labels = self._state.get("labels") or {}
        active: list[str] = []
        seen: set[str] = set()
        for label, state in labels.items():
            canonical = _canonical_label(label)
            if canonical in seen:
                continue
            if isinstance(state, dict) and _label_state_is_active(state):
                active.append(canonical)
                seen.add(canonical)
        for label, addresses in self._last_scan_by_label.items():
            canonical = _canonical_label(label)
            if canonical not in seen and addresses:
                active.append(canonical)
                seen.add(canonical)
        return active

    def _ambiguous_label_result(self, action: AgentAction, labels: list[str]) -> ActionResult:
        label_text = "、".join(labels)
        return ActionResult(
            action=action,
            ok=False,
            message=f"当前有多个扫描会话：{label_text}。请说明要继续哪个数值，例如：现在{labels[0]}是新的数值。",
            data={
                "ambiguous_labels": labels,
                "next_step": f"请带上标签继续，例如：现在{labels[0]}是新的数值。",
            },
        )

    def _migrate_state_labels(self) -> None:
        labels = self._state.get("labels")
        if not isinstance(labels, dict):
            return
        for label in list(labels.keys()):
            self._merge_label_aliases(_canonical_label(label))

    def _merge_label_aliases(self, canonical: str) -> None:
        canonical = _canonical_label(canonical)
        labels = self._state.setdefault("labels", {})
        changed = False
        for label in list(labels.keys()):
            if label == canonical or _canonical_label(label) != canonical:
                continue
            source = labels.pop(label)
            target = labels.setdefault(canonical, {})
            if isinstance(target, dict) and isinstance(source, dict):
                _merge_label_state(target, source)
            changed = True

        for label in list(self._last_scan_by_label.keys()):
            if label == canonical or _canonical_label(label) != canonical:
                continue
            addresses = self._last_scan_by_label.pop(label)
            current = self._last_scan_by_label.get(canonical)
            if not current or (addresses and len(addresses) <= len(current)):
                self._last_scan_by_label[canonical] = addresses
            changed = True

        for label in list(self._last_string_wide_by_label.keys()):
            if label == canonical or _canonical_label(label) != canonical:
                continue
            wide = self._last_string_wide_by_label.pop(label)
            self._last_string_wide_by_label.setdefault(canonical, wide)
            changed = True

        if changed:
            self._save_state()

    def _load_state(self) -> dict[str, Any]:
        try:
            if self.state_path.exists():
                return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {}

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _try_get_scan_results(self) -> Any:
        try:
            return self._call("get_scan_results", {"max": self.max_scan_results})
        except MCPError:
            return None

    def _call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        client = self._get_client()
        try:
            return client.call_tool(tool_name, arguments)
        except (MCPError, OSError) as exc:
            if _should_reset_mcp_client(str(exc)):
                self.close()
            raise

    def _get_client(self) -> MCPStdioClient:
        if self._client is None:
            self._client = MCPStdioClient(self.command, self.args, timeout_seconds=self.timeout_seconds)
            self._client.start()
        return self._client


def _is_error_result(result: Any) -> bool:
    return isinstance(result, dict) and result.get("success") is False


def _write_confirmed(write_result: Any, readback: Any, expected: Any) -> bool:
    if _is_error_result(write_result) or _is_error_result(readback):
        return False
    read_value = _extract_scalar_field(readback, "value")
    if read_value is None:
        return False
    return _values_equal(read_value, expected)


def _coerce_numeric_value(value: Any, value_type: str) -> int | float:
    normalized_type = value_type.lower()
    if normalized_type in {"float", "double"}:
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if text.lower().startswith(("0x", "-0x", "+0x")):
            return int(text, 16)
    return int(value)


def _followups_ok(followup: dict[str, Any]) -> bool:
    write = followup.get("write") if isinstance(followup, dict) else None
    return not isinstance(write, dict) or bool(write.get("ok"))


def _is_unique_candidate(addresses: list[str], total: int | None) -> bool:
    return len(addresses) == 1 and total == 1


def _write_error_message(write_result: Any, readback: Any, expected: Any) -> str:
    if _is_error_result(write_result):
        return str(write_result.get("error") or "write_integer failed")
    if _is_error_result(readback):
        return str(readback.get("error") or "read_integer failed")
    read_value = _extract_scalar_field(readback, "value")
    if read_value is not None and not _values_equal(read_value, expected):
        return f"readback mismatch: expected {expected}, got {read_value}"
    return "write result was not confirmed"


def _extract_scalar_field(value: Any, field_name: str) -> Any:
    if isinstance(value, dict):
        if field_name in value and not isinstance(value[field_name], (dict, list)):
            return value[field_name]
        for nested in value.values():
            found = _extract_scalar_field(nested, field_name)
            if found is not None:
                return found
    if isinstance(value, list):
        for item in value:
            found = _extract_scalar_field(item, field_name)
            if found is not None:
                return found
    return None


def _values_equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, float) or isinstance(expected, float):
        try:
            return abs(float(actual) - float(expected)) <= 1e-6
        except (TypeError, ValueError):
            return str(actual) == str(expected)
    try:
        return int(actual) == int(expected)
    except (TypeError, ValueError):
        return str(actual) == str(expected)


def _brief_result(prefix: str, result: Any) -> str:
    if isinstance(result, dict):
        if result.get("success") is False:
            return f"{prefix}: {result.get('error', 'failed')}"
        text = json.dumps(result, ensure_ascii=False)
        return f"{prefix}: {text[:240]}"
    return f"{prefix}: {str(result)[:240]}"


def _extract_total_count(result: Any) -> int | None:
    if isinstance(result, dict):
        for key in ("total", "total_count", "match_count", "matches", "found_count"):
            value = result.get(key)
            if isinstance(value, int):
                return value
        if "count" in result and "returned" not in result:
            value = result.get("count")
            if isinstance(value, int):
                return value
        for value in result.values():
            nested = _extract_total_count(value)
            if nested is not None:
                return nested
    return None


def _friendly_error(message: str) -> str:
    if "Pipe not found" in message or "CE_MCP_Bridge" in message:
        bridge_path = PROJECT_ROOT / "runtime" / "ce_mcp" / "ce_mcp_bridge.lua"
        return (
            f"{message}. Start Cheat Engine, execute "
            f"{bridge_path}, "
            "and close other MCP clients if the bridge pipe is already occupied."
        )
    return message


def _should_reset_mcp_client(message: str) -> bool:
    lowered = message.lower()
    return any(
        marker in lowered
        for marker in (
            "timed out",
            "closed stdout",
            "server exited",
            "broken pipe",
            "pipe not found",
            "ce_mcp_bridge",
        )
    )


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _process_id_matches(expected_pid: int, process_info: Any) -> bool:
    observed_pid = _extract_scalar_field(process_info, "process_id")
    return _values_equal(observed_pid, expected_pid) if observed_pid is not None else False


def _process_matches(expected: str, process_info: Any) -> bool:
    expected_names = _process_name_variants(expected)
    observed: set[str] = set()
    if isinstance(process_info, dict):
        for key in ("process_name", "name", "process"):
            value = process_info.get(key)
            if isinstance(value, str):
                observed.update(_process_name_variants(value))
        modules = process_info.get("modules")
        if isinstance(modules, list):
            for module in modules[:5]:
                if isinstance(module, dict):
                    name = module.get("name")
                    path = module.get("path")
                    if isinstance(name, str):
                        observed.update(_process_name_variants(name))
                    if isinstance(path, str):
                        observed.update(_process_name_variants(Path(path).name))
    return bool(expected_names & observed)


def _process_name_variants(value: str) -> set[str]:
    raw = value.strip().strip('"').strip("'")
    if not raw:
        return set()
    name = Path(raw).name.lower()
    stem = Path(name).stem.lower()
    variants = {name, stem}
    if not name.endswith(".exe"):
        variants.add(f"{name}.exe")
    if stem:
        variants.add(f"{stem}.exe")
    return {item for item in variants if item}


_LABEL_ALIASES = {
    "sun": "阳光",
    "sunlight": "阳光",
    "sunshine": "阳光",
    "太阳": "阳光",
    "阳光": "阳光",
    "coin": "金币",
    "coins": "金币",
    "gold": "金币",
    "money": "金币",
    "cash": "金币",
    "金币": "金币",
    "金钱": "金币",
    "钱": "金币",
    "hp": "血量",
    "health": "血量",
    "life": "血量",
    "lives": "血量",
    "血量": "血量",
    "生命": "血量",
    "score": "分数",
    "scores": "分数",
    "point": "分数",
    "points": "分数",
    "分数": "分数",
    "积分": "分数",
    "ammo": "弹药",
    "bullet": "弹药",
    "bullets": "弹药",
    "弹药": "弹药",
    "子弹": "弹药",
    "exp": "经验",
    "xp": "经验",
    "experience": "经验",
    "经验": "经验",
}

_PLACEHOLDER_LABELS = {
    "",
    "value",
    "current",
    "current_value",
    "target",
    "target_value",
    "unknown",
    "数值",
    "当前值",
    "目标值",
    "变量",
}


def _canonical_label(value: Any) -> str:
    text = str(value or "").strip().strip("，。,. 的")
    if not text:
        return "value"
    lowered = text.lower()
    alias = _LABEL_ALIASES.get(lowered) or _LABEL_ALIASES.get(text)
    if alias:
        return alias
    if lowered in _PLACEHOLDER_LABELS:
        return lowered
    return text


def _is_placeholder_label(label: str) -> bool:
    return _canonical_label(label).lower() in _PLACEHOLDER_LABELS


def _label_state_is_active(state: dict[str, Any]) -> bool:
    addresses = state.get("addresses")
    return bool(
        state.get("pending_write")
        or state.get("pending_base")
        or state.get("final_address")
        or (isinstance(addresses, list) and addresses)
    )


def _merge_label_state(target: dict[str, Any], source: dict[str, Any]) -> None:
    source_addresses = list(source.get("addresses") or [])
    target_addresses = list(target.get("addresses") or [])
    source_total = source.get("total")
    target_total = target.get("total")
    source_wins = source_addresses and (
        not target_addresses
        or _candidate_rank(source, source_total, len(source_addresses)) < _candidate_rank(target, target_total, len(target_addresses))
    )
    if source_wins:
        target["addresses"] = source_addresses
        target["total"] = source_total if isinstance(source_total, int) else None
        target["total_known"] = _state_has_known_total(source, source_total, len(source_addresses))
        for key in ("last_value", "value_type", "final_address", "completed"):
            if key in source:
                target[key] = source[key]
    elif not target_addresses:
        for key in ("last_value", "value_type", "final_address", "completed"):
            if key in source and key not in target:
                target[key] = source[key]
    for key in ("pending_write", "pending_base"):
        if source.get(key):
            target[key] = source[key]


def _candidate_rank(state: dict[str, Any], total: Any, visible_count: int) -> tuple[int, int]:
    if _state_has_known_total(state, total, visible_count):
        return (0, int(total))
    return (1, visible_count)


def _state_has_known_total(state: dict[str, Any], total: Any, visible_count: int) -> bool:
    if not isinstance(total, int):
        return False
    if state.get("total_known") is True:
        return True
    return total > visible_count


def _next_step_for_candidates(label: str, total: int | None, visible_count: int) -> str | None:
    if visible_count == 0 and not total:
        return f"没有找到 {label} 候选。请确认 Cheat Engine 已附加到正确进程，并重新告诉我当前{label}值。"
    if visible_count == 1 and total == 1:
        return None
    return f"请在目标程序里让{label}变化一次，然后告诉我新的{label}数值，例如：现在{label}是50了。"


def _collect_address_strings(value: Any, output: list[str]) -> None:
    if isinstance(value, str):
        if value.startswith("0x") or value.startswith("0X"):
            output.append(value)
        return
    if isinstance(value, list):
        for item in value:
            _collect_address_strings(item, output)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in {"address", "base_address", "addr"}:
                _collect_address_strings(item, output)
            elif isinstance(item, (dict, list)):
                _collect_address_strings(item, output)


def _extract_addresses(result: Any) -> list[str]:
    addresses: list[str] = []
    _collect_address_strings(result, addresses)
    deduped: list[str] = []
    seen: set[str] = set()
    for address in addresses:
        normalized = address.upper().replace("0X", "0x", 1)
        if normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped
