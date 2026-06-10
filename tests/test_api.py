import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from cheatpilot import api
from cheatpilot.models import ActionResult, ActionType, AgentAction, AgentPlan, AgentResponse


def response_for(action_type: ActionType, *, ok: bool) -> AgentResponse:
    action = AgentAction(type=action_type, arguments={}, reason="test")
    return AgentResponse(
        plan=AgentPlan.create(original_message="test", actions=[action], summary="test"),
        results=[ActionResult(action=action, ok=ok, message="test", data={})],
    )


class RecordingExecutor:
    def __init__(self) -> None:
        self.actions = []

    def execute(self, action: AgentAction) -> ActionResult:
        self.actions.append(action)
        return ActionResult(action=action, ok=True, message=f"ran {action.type.value}", data={})


class FakeChatAgent:
    def __init__(self) -> None:
        self.messages = []

    def handle(self, message: str) -> AgentResponse:
        self.messages.append(message)
        action = AgentAction(type=ActionType.EXPLAIN, arguments={"text": "普通回复"}, reason="test")
        return AgentResponse(
            plan=AgentPlan.create(original_message=message, actions=[action], summary="test"),
            results=[ActionResult(action=action, ok=True, message="普通回复", data={})],
            assistant_message="普通回复",
        )


class ApiSessionOwnerTest(unittest.TestCase):
    def setUp(self) -> None:
        api._ce_session_owner = None
        api._agents.clear()

    def tearDown(self) -> None:
        api._ce_session_owner = None
        api._agents.clear()

    def test_failed_ce_action_does_not_claim_owner(self) -> None:
        api._update_ce_session_owner("s1", response_for(ActionType.ATTACH_PROCESS, ok=False))

        self.assertIsNone(api._ce_session_owner)

    def test_successful_ce_action_claims_owner(self) -> None:
        api._update_ce_session_owner("s1", response_for(ActionType.ATTACH_PROCESS, ok=True))

        self.assertEqual(api._ce_session_owner, "s1")

    def test_takeover_requires_successful_ce_action(self) -> None:
        api._ce_session_owner = "s1"

        api._update_ce_session_owner("s2", response_for(ActionType.ATTACH_PROCESS, ok=False), allow_takeover=True)
        self.assertEqual(api._ce_session_owner, "s1")

        api._update_ce_session_owner("s2", response_for(ActionType.ATTACH_PROCESS, ok=True), allow_takeover=True)
        self.assertEqual(api._ce_session_owner, "s2")

    def test_reset_releases_only_on_success(self) -> None:
        api._ce_session_owner = "s1"

        api._update_ce_session_owner("s1", response_for(ActionType.RESET_SESSION, ok=False))
        self.assertEqual(api._ce_session_owner, "s1")

        api._update_ce_session_owner("s1", response_for(ActionType.RESET_SESSION, ok=True))
        self.assertIsNone(api._ce_session_owner)

    def test_non_ce_action_is_not_blocked_by_other_session_owner(self) -> None:
        api._ce_session_owner = "s1"
        inner = RecordingExecutor()
        executor = api._ApiSessionExecutor(session_id="s2", inner=inner)
        action = AgentAction(type=ActionType.RUN_COMMAND, arguments={"command": "echo ok"})

        result = executor.execute(action)

        self.assertTrue(result.ok)
        self.assertEqual(inner.actions, [action])

    def test_ce_action_is_blocked_by_other_session_owner(self) -> None:
        api._ce_session_owner = "s1"
        inner = RecordingExecutor()
        executor = api._ApiSessionExecutor(session_id="s2", inner=inner)
        action = AgentAction(type=ActionType.SCAN_EXACT_VALUE, arguments={"label": "金币", "value": 100})

        result = executor.execute(action)

        self.assertFalse(result.ok)
        self.assertEqual(result.data["error"], "ce_session_busy")
        self.assertEqual(inner.actions, [])

    def test_takeover_allows_ce_action_to_execute(self) -> None:
        api._ce_session_owner = "s1"
        inner = RecordingExecutor()
        executor = api._ApiSessionExecutor(session_id="s2", inner=inner)
        executor.allow_takeover = True
        action = AgentAction(type=ActionType.SCAN_EXACT_VALUE, arguments={"label": "金币", "value": 100})

        result = executor.execute(action)

        self.assertTrue(result.ok)
        self.assertEqual(inner.actions, [action])

    def test_chat_endpoint_does_not_block_plain_agent_reply_when_ce_owned_elsewhere(self) -> None:
        api._ce_session_owner = "s1"
        agent = FakeChatAgent()
        client = TestClient(api.app)

        with patch("cheatpilot.api.build_agent", return_value=agent):
            response = client.post("/chat", json={"session_id": "s2", "message": "你好"})

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["reply"], "普通回复")
        self.assertEqual(payload["ce_session_owner"], "s1")
        self.assertEqual(agent.messages, ["你好"])


if __name__ == "__main__":
    unittest.main()
