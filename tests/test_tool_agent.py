import unittest
import urllib.error
from unittest.mock import patch

from cheatpilot.models import ActionResult, ActionType
from cheatpilot.tool_agent import ToolUseChatAgent, _is_retryable_http_error, _retry_delay_seconds


class RecordingExecutor:
    def __init__(self) -> None:
        self.actions = []

    def execute(self, action):
        self.actions.append(action)
        return ActionResult(action=action, ok=True, message=f"ran {action.type.value}", data={"arguments": action.arguments})


class FakeToolAgent(ToolUseChatAgent):
    def __init__(self, executor):
        super().__init__(executor=executor, base_url="http://fake/v1", api_key="key", model="fake")
        self.calls = 0

    def _chat(self, messages, *, tools=None):
        self.calls += 1
        if self.calls == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "attach_process", "arguments": '{"process":"game.exe"}'},
                                },
                                {
                                    "id": "call_2",
                                    "type": "function",
                                    "function": {"name": "scan_exact_value", "arguments": '{"label":"金币","value":150}'},
                                },
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"role": "assistant", "content": "工具调用完成。"}}]}


class NoToolFakeAgent(ToolUseChatAgent):
    def __init__(self, executor):
        super().__init__(executor=executor, base_url="http://fake/v1", api_key="key", model="fake")
        self.seen_user_messages = []

    def _chat(self, messages, *, tools=None):
        self.seen_user_messages.append(messages[-1]["content"])
        return {"choices": [{"message": {"role": "assistant", "content": "LLM 已收到。"}}]}


class ResetToolFakeAgent(ToolUseChatAgent):
    def __init__(self, executor):
        super().__init__(executor=executor, base_url="http://fake/v1", api_key="key", model="fake")
        self.calls = 0

    def _chat(self, messages, *, tools=None):
        self.calls += 1
        if self.calls == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_reset",
                                    "type": "function",
                                    "function": {"name": "reset_session", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"role": "assistant", "content": "已让工具清空会话。"}}]}


class LegacyFunctionCallAgent(ToolUseChatAgent):
    def __init__(self, executor):
        super().__init__(executor=executor, base_url="http://fake/v1", api_key="key", model="fake")
        self.calls = 0

    def _chat(self, messages, *, tools=None):
        self.calls += 1
        if self.calls == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "function_call": {"name": "session_status", "arguments": '{"label":"金币"}'},
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"role": "assistant", "content": "旧格式工具调用完成。"}}]}


class ToolUseChatAgentTest(unittest.TestCase):
    def test_llm_tool_calls_execute_actions(self) -> None:
        executor = RecordingExecutor()
        response = FakeToolAgent(executor).handle("请用工具处理这个复杂内存任务")

        self.assertTrue(response.ok)
        self.assertEqual([action.type for action in executor.actions], [ActionType.ATTACH_PROCESS, ActionType.SCAN_EXACT_VALUE])
        self.assertEqual(response.plan.actions[0].arguments["process"], "game.exe")
        self.assertEqual(response.plan.actions[1].arguments["label"], "金币")
        self.assertEqual(response.assistant_message, "工具调用完成。")

    def test_plain_chat_still_goes_to_llm(self) -> None:
        executor = RecordingExecutor()
        agent = NoToolFakeAgent(executor)
        response = agent.handle("你好")

        self.assertEqual(agent.seen_user_messages, ["你好"])
        self.assertEqual(executor.actions, [])
        self.assertEqual(response.assistant_message, "LLM 已收到。")

    def test_reset_request_is_not_handled_locally(self) -> None:
        executor = RecordingExecutor()
        response = ResetToolFakeAgent(executor).handle("重新开始")

        self.assertEqual([action.type for action in executor.actions], [ActionType.RESET_SESSION])
        self.assertEqual(response.assistant_message, "已让工具清空会话。")

    def test_legacy_function_call_executes_action(self) -> None:
        executor = RecordingExecutor()
        response = LegacyFunctionCallAgent(executor).handle("查看金币扫描状态")

        self.assertTrue(response.ok)
        self.assertEqual([action.type for action in executor.actions], [ActionType.SESSION_STATUS])
        self.assertEqual(response.plan.actions[0].arguments["label"], "金币")
        self.assertEqual(response.assistant_message, "旧格式工具调用完成。")

    def test_http_429_is_retryable(self) -> None:
        error = urllib.error.HTTPError("http://fake/v1/chat/completions", 429, "Too Many Requests", {}, None)

        self.assertTrue(_is_retryable_http_error(error))
        self.assertGreaterEqual(_retry_delay_seconds(0, error), 5.0)

    def test_chat_retries_after_http_429(self) -> None:
        executor = RecordingExecutor()
        agent = ToolUseChatAgent(executor=executor, base_url="http://fake/v1", api_key="key", model="fake", max_retries=1)
        error = urllib.error.HTTPError("http://fake/v1/chat/completions", 429, "Too Many Requests", {}, None)

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return None

            def read(self):
                return b'{"choices":[{"message":{"role":"assistant","content":"ok"}}]}'

        with patch("cheatpilot.tool_agent.time.sleep") as sleep, patch("cheatpilot.tool_agent.urllib.request.urlopen", side_effect=[error, FakeResponse()]) as urlopen:
            response = agent._chat([{"role": "user", "content": "hi"}])

        self.assertEqual(response["choices"][0]["message"]["content"], "ok")
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
