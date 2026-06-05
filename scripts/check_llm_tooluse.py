from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cheatpilot.config import CheatPilotConfig
from cheatpilot.tool_agent import ToolUseChatAgent, tool_schemas


def main() -> int:
    config = CheatPilotConfig.from_env()
    agent = ToolUseChatAgent(
        executor=None,  # type: ignore[arg-type]
        base_url=config.llm_base_url,
        api_key=config.llm_api_key,
        model=config.llm_model,
        timeout_seconds=max(config.llm_timeout_seconds, 30.0),
    )
    response = agent._chat(
        [
            {"role": "system", "content": "You are a tool-use test agent. Use tools when appropriate."},
            {"role": "user", "content": "请调用 session_status 工具查看 value 状态。"},
        ],
        tools=tool_schemas(),
    )
    message = response["choices"][0]["message"]
    print(json.dumps({"model": config.llm_model, "message": message}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
