from __future__ import annotations

from typing import Protocol

from cheatpilot.models import ActionResult, AgentAction


class MemoryExecutor(Protocol):
    def execute(self, action: AgentAction) -> ActionResult:
        """Execute one planned action and return a structured result."""
