from __future__ import annotations

from cheatpilot.executors.base import MemoryExecutor
from cheatpilot.models import ActionResult, ActionType, AgentResponse
from cheatpilot.planner import Planner


class CheatPilotAgent:
    """Coordinates planning and execution for one natural-language request."""

    def __init__(
        self,
        *,
        planner: Planner,
        executor: MemoryExecutor,
    ) -> None:
        self.planner = planner
        self.executor = executor

    def handle(self, message: str) -> AgentResponse:
        normalized = message.strip()
        if not normalized:
            raise ValueError("message cannot be empty")

        plan = self.planner.plan(normalized)
        results: list[ActionResult] = []
        for action in plan.actions:
            result = self.executor.execute(action)
            results.append(result)
            if result.data.get("fatal") or (action.type == ActionType.ATTACH_PROCESS and not result.ok):
                break

        return AgentResponse(plan=plan, results=results)

    def close(self) -> None:
        close = getattr(self.executor, "close", None)
        if callable(close):
            close()
