import unittest

from cheatpilot.config import CheatPilotConfig
from cheatpilot.factory import build_agent
from cheatpilot.tool_agent import ToolUseChatAgent


class FactoryTest(unittest.TestCase):
    def test_tool_agent_runtime_knobs_are_injected_from_config(self) -> None:
        agent = build_agent(
            config=CheatPilotConfig(
                llm_base_url="http://fake/v1",
                llm_api_key="key",
                llm_model="fake",
                max_tool_rounds=17,
                max_history_messages=33,
            )
        )

        self.assertIsInstance(agent, ToolUseChatAgent)
        self.assertEqual(agent.max_tool_rounds, 17)
        self.assertEqual(agent.max_history_messages, 33)


if __name__ == "__main__":
    unittest.main()
