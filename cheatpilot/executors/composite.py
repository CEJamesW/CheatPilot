from __future__ import annotations

from dataclasses import dataclass

from cheatpilot.executors.base import MemoryExecutor
from cheatpilot.executors.local_tools import LocalToolExecutor
from cheatpilot.models import ActionResult, ActionType, AgentAction


LOCAL_ACTIONS = {
    ActionType.THINK,
    ActionType.LIST_FILES,
    ActionType.READ_FILE,
    ActionType.WRITE_FILE,
    ActionType.RUN_COMMAND,
}


@dataclass(slots=True)
class CompositeExecutor:
    """Route tool-use actions to Cheat Engine MCP or local agent tools."""

    memory_executor: MemoryExecutor
    local_executor: LocalToolExecutor

    def execute(self, action: AgentAction) -> ActionResult:
        if action.type in LOCAL_ACTIONS:
            return self.local_executor.execute(action)
        return self.memory_executor.execute(action)

    def close(self) -> None:
        close = getattr(self.memory_executor, "close", None)
        if callable(close):
            close()
