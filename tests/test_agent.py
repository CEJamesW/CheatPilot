import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cheatpilot.agent import CheatPilotAgent
from cheatpilot.executors.ce_mcp import CheatEngineMCPExecutor, _extract_total_count, _is_unique_candidate, _process_matches
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


class RecordingMCPExecutor(CheatEngineMCPExecutor):
    def __init__(self, *args, responses=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = []
        self.responses = list(responses or [])

    def _call(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        if self.responses:
            return self.responses.pop(0)
        return {"success": True}


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

    def test_saved_preview_address_does_not_become_confirmed_total(self) -> None:
        with TemporaryDirectory() as temp_dir:
            executor = CheatEngineMCPExecutor(state_path=Path(temp_dir) / "state.json")
            executor._remember_scan("金币", ["0x1000"], None, "150", "dword")

            addresses, total = executor._candidate_info("金币")

        self.assertEqual(addresses, ["0x1000"])
        self.assertIsNone(total)
        self.assertFalse(_is_unique_candidate(addresses, total))


class NumericValueTypeTest(unittest.TestCase):
    def test_decimal_scan_infers_float_when_value_type_is_omitted(self) -> None:
        with TemporaryDirectory() as temp_dir:
            executor = RecordingMCPExecutor(
                state_path=Path(temp_dir) / "state.json",
                responses=[{"success": True, "results": [{"address": "0x1000"}], "total": 1}],
            )
            action = AgentAction(type=ActionType.SCAN_EXACT_VALUE, arguments={"label": "速度", "value": "12.5"})

            result = executor.execute(action)

        self.assertTrue(result.ok)
        self.assertEqual(executor.calls[0], ("scan_all", {"value": "12.5", "type": "float", "protection": "+W-C"}))

    def test_write_reuses_scan_value_type_when_llm_omits_it(self) -> None:
        with TemporaryDirectory() as temp_dir:
            executor = RecordingMCPExecutor(
                state_path=Path(temp_dir) / "state.json",
                responses=[
                    {"success": True},
                    {"success": True, "value": 99.5},
                ],
            )
            executor._remember_scan("速度", ["0x1000"], 1, "12.5", "float")
            action = AgentAction(type=ActionType.WRITE_VALUE, arguments={"label": "速度", "value": "99.5"})

            result = executor.execute(action)

        self.assertTrue(result.ok)
        self.assertEqual(executor.calls[0], ("write_integer", {"address": "0x1000", "value": 99.5, "type": "float"}))
        self.assertEqual(executor.calls[1], ("read_integer", {"address": "0x1000", "type": "float"}))


if __name__ == "__main__":
    unittest.main()
