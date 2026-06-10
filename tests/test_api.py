import unittest

from cheatpilot import api
from cheatpilot.models import ActionResult, ActionType, AgentAction, AgentPlan, AgentResponse


def response_for(action_type: ActionType, *, ok: bool) -> AgentResponse:
    action = AgentAction(type=action_type, arguments={}, reason="test")
    return AgentResponse(
        plan=AgentPlan.create(original_message="test", actions=[action], summary="test"),
        results=[ActionResult(action=action, ok=ok, message="test", data={})],
    )


class ApiSessionOwnerTest(unittest.TestCase):
    def setUp(self) -> None:
        api._ce_session_owner = None

    def tearDown(self) -> None:
        api._ce_session_owner = None

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


if __name__ == "__main__":
    unittest.main()
