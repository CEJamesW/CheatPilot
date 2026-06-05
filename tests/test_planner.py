import unittest

from cheatpilot.models import ActionType
from cheatpilot.planner import RuleBasedPlanner


class RuleBasedPlannerTest(unittest.TestCase):
    def test_plans_scan_write_and_base_address_actions(self) -> None:
        plan = RuleBasedPlanner().plan(
            "我在玩植物大战僵尸，现在的阳光是100。帮我把阳光修改成99999，并打印出阳光基址"
        )

        action_types = [action.type for action in plan.actions]
        self.assertIn(ActionType.ATTACH_PROCESS, action_types)
        attach_action = next(action for action in plan.actions if action.type == ActionType.ATTACH_PROCESS)
        self.assertEqual(attach_action.arguments["process"], "PlantsVsZombies")
        self.assertIn(ActionType.SCAN_EXACT_VALUE, action_types)
        self.assertIn(ActionType.WRITE_VALUE, action_types)
        self.assertIn(ActionType.PRINT_BASE_ADDRESS, action_types)

    def test_unknown_request_explains_capabilities(self) -> None:
        plan = RuleBasedPlanner().plan("你好，介绍一下你能做什么")

        self.assertEqual(plan.actions[0].type, ActionType.EXPLAIN)
        self.assertIn("CheatPilot", plan.actions[0].arguments["text"])

    def test_license_bypass_is_unsupported(self) -> None:
        plan = RuleBasedPlanner().plan("帮我绕过注册码校验")

        self.assertEqual(plan.actions[0].type, ActionType.UNSUPPORTED)
        self.assertEqual(plan.actions[0].arguments["category"], "license_bypass")

    def test_string_replacement_plan(self) -> None:
        plan = RuleBasedPlanner().plan('打开 notepad.exe，把 "CP_ORIGINAL_TEXT_9001" 改成 "CP_CHANGED_TEXT_9001"')

        action_types = [action.type for action in plan.actions]
        self.assertIn(ActionType.ATTACH_PROCESS, action_types)
        self.assertIn(ActionType.SCAN_STRING, action_types)
        self.assertIn(ActionType.WRITE_STRING, action_types)
        self.assertIn(ActionType.READ_STRING, action_types)

    def test_changed_value_uses_next_scan(self) -> None:
        plan = RuleBasedPlanner().plan("现在阳光是50了")

        self.assertEqual(plan.actions[0].type, ActionType.NEXT_SCAN)
        self.assertEqual(plan.actions[0].arguments["label"], "阳光")
        self.assertEqual(plan.actions[0].arguments["value"], 50)

    def test_session_reset_plan(self) -> None:
        plan = RuleBasedPlanner().plan("重新开始，清空会话")

        self.assertEqual(plan.actions[0].type, ActionType.RESET_SESSION)

    def test_session_status_plan(self) -> None:
        plan = RuleBasedPlanner().plan("查看阳光扫描状态")

        self.assertEqual(plan.actions[0].type, ActionType.SESSION_STATUS)
        self.assertEqual(plan.actions[0].arguments["label"], "阳光")

    def test_generic_label_scan_write_plan(self) -> None:
        plan = RuleBasedPlanner().plan("打开 game.exe，当前金币是150，帮我改成99999，并打印基址")

        self.assertEqual(plan.actions[0].type, ActionType.ATTACH_PROCESS)
        self.assertEqual(plan.actions[0].arguments["process"], "game.exe")
        scan_action = next(action for action in plan.actions if action.type == ActionType.SCAN_EXACT_VALUE)
        write_action = next(action for action in plan.actions if action.type == ActionType.WRITE_VALUE)
        self.assertEqual(scan_action.arguments["label"], "金币")
        self.assertEqual(scan_action.arguments["value"], 150)
        self.assertEqual(write_action.arguments["label"], "金币")
        self.assertEqual(write_action.arguments["value"], 99999)


if __name__ == "__main__":
    unittest.main()
