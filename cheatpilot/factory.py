from __future__ import annotations

from cheatpilot.agent import CheatPilotAgent
from cheatpilot.config import CheatPilotConfig
from cheatpilot.executors.ce_mcp import CheatEngineMCPExecutor
from cheatpilot.executors.composite import CompositeExecutor
from cheatpilot.executors.local_tools import LocalToolExecutor
from cheatpilot.planner import HybridPlanner, OpenAICompatiblePlanner, RuleBasedPlanner
from cheatpilot.tool_agent import ToolUseChatAgent


def build_agent(
    *,
    planner_name: str | None = None,
    config: CheatPilotConfig | None = None,
) -> CheatPilotAgent | ToolUseChatAgent:
    cfg = config or CheatPilotConfig.from_env()
    selected_planner = (planner_name or cfg.planner).lower()
    ce_executor = CheatEngineMCPExecutor(
        command=cfg.mcp_command,
        args=cfg.mcp_args or [],
        allow_lua_actions=cfg.allow_lua_actions,
        value_type=cfg.value_type,
        max_scan_results=cfg.max_scan_results,
    )
    executor = CompositeExecutor(memory_executor=ce_executor, local_executor=LocalToolExecutor())

    if selected_planner in {"llm", "tool", "tooluse", "tool-use"}:
        return ToolUseChatAgent(
            executor=executor,
            base_url=cfg.llm_base_url,
            api_key=cfg.llm_api_key,
            model=cfg.llm_model,
            timeout_seconds=cfg.llm_timeout_seconds,
            max_retries=cfg.llm_max_retries,
        )
    if selected_planner == "hybrid":
        planner = HybridPlanner(
            OpenAICompatiblePlanner(
                base_url=cfg.llm_base_url,
                api_key=cfg.llm_api_key,
                model=cfg.llm_model,
                timeout_seconds=cfg.llm_timeout_seconds,
            )
        )
    elif selected_planner == "openai":
        planner = OpenAICompatiblePlanner(
            base_url=cfg.llm_base_url,
            api_key=cfg.llm_api_key,
            model=cfg.llm_model,
            timeout_seconds=cfg.llm_timeout_seconds,
        )
    elif selected_planner == "rule":
        planner = RuleBasedPlanner()
    else:
        raise ValueError(f"unknown planner: {selected_planner}")

    return CheatPilotAgent(planner=planner, executor=executor)
