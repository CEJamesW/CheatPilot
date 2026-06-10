import unittest

from cheatpilot.agent import CheatPilotAgent
from cheatpilot.executors.ce_mcp import _extract_total_count, _is_unique_candidate, _process_matches
from cheatpilot.models import ActionResult, ActionType, AgentAction, AgentPlan


class StaticPlanner:
    def __init__(self, actions):
        self.actions = actions

    def plan(self, message: str) -> AgentPlan:
        return AgentPlan.create(original_message=message, actions=self.actions, summary="static")


class StaticExecutor:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def execute(self, action: AgentAction) -> ActionResult:
        self.calls.append(action)
        return self.results.pop(0)


class AgentTest(unittest.TestCase):
    def test_stops_after_failed_attach(self) -> None:
        attach = AgentAction(type=ActionType.ATTACH_PROCESS, arguments={"process": "game.exe"})
        scan = AgentAction(type=ActionType.SCAN_EXACT_VALUE, arguments={"label": "金币", "value": 150})
        failed = ActionResult(action=attach, ok=False, message="attach failed", data={"fatal": True})
        executor = StaticExecutor([failed])

        response = CheatPilotAgent(planner=StaticPlanner([attach, scan]), executor=executor).handle("go")

        self.assertFalse(response.ok)
        self.assertEqual(len(executor.calls), 1)
        self.assertEqual(executor.calls[0].type, ActionType.ATTACH_PROCESS)


class ProcessMatchTest(unittest.TestCase):
    def test_process_match_accepts_main_module(self) -> None:
        self.assertTrue(
            _process_matches(
                "PlantsVsZombies",
                {"process_name": "PlantsVsZombies.exe", "modules": [{"name": "PlantsVsZombies.exe"}]},
            )
        )

    def test_process_match_rejects_stale_process(self) -> None:
        self.assertFalse(
            _process_matches(
                "game.exe",
                {"process_name": "PlantsVsZombies.exe", "modules": [{"name": "PlantsVsZombies.exe"}]},
            )
        )


class ScanCountTest(unittest.TestCase):
    def test_returned_count_is_not_treated_as_total(self) -> None:
        result = {"success": True, "results": [{"address": "0x1000"}], "returned": 1}

        self.assertIsNone(_extract_total_count(result))

    def test_total_preferred_over_returned(self) -> None:
        result = {"success": True, "results": [{"address": "0x1000"}], "total": 25, "returned": 1}

        self.assertEqual(_extract_total_count(result), 25)

    def test_plain_scan_count_is_total(self) -> None:
        result = {"success": True, "count": 1}

        self.assertEqual(_extract_total_count(result), 1)

    def test_unique_candidate_requires_known_total(self) -> None:
        self.assertFalse(_is_unique_candidate(["0x1000"], None))
        self.assertFalse(_is_unique_candidate(["0x1000"], 2))
        self.assertTrue(_is_unique_candidate(["0x1000"], 1))


if __name__ == "__main__":
    unittest.main()
