from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4


class ActionType(StrEnum):
    THINK = "think"
    ATTACH_PROCESS = "attach_process"
    GET_PROCESS_INFO = "get_process_info"
    SESSION_STATUS = "session_status"
    RESET_SESSION = "reset_session"
    SCAN_EXACT_VALUE = "scan_exact_value"
    NEXT_SCAN = "next_scan"
    WRITE_VALUE = "write_value"
    PRINT_BASE_ADDRESS = "print_base_address"
    READ_VALUE = "read_value"
    SCAN_STRING = "scan_string"
    READ_STRING = "read_string"
    SCAN_AOB = "scan_aob"
    WRITE_BYTES = "write_bytes"
    WRITE_STRING = "write_string"
    EVALUATE_LUA = "evaluate_lua"
    CE_MCP_CALL = "ce_mcp_call"
    LIST_FILES = "list_files"
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    RUN_COMMAND = "run_command"
    EXPLAIN = "explain"
    UNSUPPORTED = "unsupported"


@dataclass(slots=True)
class AgentAction:
    type: ActionType
    arguments: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass(slots=True)
class AgentPlan:
    id: str
    original_message: str
    actions: list[AgentAction]
    summary: str

    @classmethod
    def create(
        cls,
        *,
        original_message: str,
        actions: list[AgentAction],
        summary: str,
    ) -> "AgentPlan":
        return cls(
            id=str(uuid4()),
            original_message=original_message,
            actions=actions,
            summary=summary,
        )


@dataclass(slots=True)
class ActionResult:
    action: AgentAction
    ok: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentResponse:
    plan: AgentPlan
    results: list[ActionResult]
    assistant_message: str | None = None

    @property
    def ok(self) -> bool:
        return all(result.ok for result in self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "assistant_message": self.assistant_message,
            "plan": {
                "id": self.plan.id,
                "original_message": self.plan.original_message,
                "summary": self.plan.summary,
                "actions": [
                    {
                        "type": action.type.value,
                        "arguments": action.arguments,
                        "reason": action.reason,
                    }
                    for action in self.plan.actions
                ],
            },
            "results": [
                {
                    "action": {
                        "type": result.action.type.value,
                        "arguments": result.action.arguments,
                        "reason": result.action.reason,
                    },
                    "ok": result.ok,
                    "message": result.message,
                    "data": result.data,
                }
                for result in self.results
            ],
        }
