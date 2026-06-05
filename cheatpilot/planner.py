from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from json import JSONDecodeError
from typing import Protocol

from cheatpilot.models import ActionType, AgentAction, AgentPlan


class Planner(Protocol):
    def plan(self, message: str) -> AgentPlan:
        """Convert a natural-language message into an executable action plan."""


class RuleBasedPlanner:
    """Small local planner used for deterministic demos and tests."""

    def plan(self, message: str) -> AgentPlan:
        actions: list[AgentAction] = []

        session_action = self._session_action(message)
        if session_action:
            return AgentPlan.create(
                original_message=message,
                actions=[session_action],
                summary="Planned 1 session action.",
            )

        prohibited_category = self._prohibited_category(message)
        if prohibited_category:
            return AgentPlan.create(
                original_message=message,
                actions=[
                    AgentAction(
                        type=ActionType.UNSUPPORTED,
                        arguments={"category": prohibited_category},
                        reason="The request is outside CheatPilot's supported action set.",
                    )
                ],
                summary="The request was classified as unsupported.",
            )

        process_name = self._extract_process_name(message)
        if process_name:
            actions.append(
                AgentAction(
                    type=ActionType.ATTACH_PROCESS,
                    arguments={"process": process_name},
                    reason="The request mentions a target process or application.",
                )
            )
        elif "进程" in message or "process" in message.lower():
            actions.append(
                AgentAction(
                    type=ActionType.GET_PROCESS_INFO,
                    arguments={},
                    reason="The request asks about the current attached process.",
                )
            )

        label = self._extract_label(message)
        string_change = self._extract_string_change(message)
        next_scan_value = self._extract_next_scan_value(message)
        current_value = self._extract_current_value(message)
        target_value = None if string_change else self._extract_target_value(message)

        if string_change:
            old_text, new_text = string_change
            actions.append(
                AgentAction(
                    type=ActionType.SCAN_STRING,
                    arguments={"label": old_text, "value": old_text, "wide": False},
                    reason="The request asks to find an existing string in memory.",
                )
            )
            actions.append(
                AgentAction(
                    type=ActionType.WRITE_STRING,
                    arguments={"label": old_text, "value": new_text, "wide": False},
                    reason="The request asks to replace the found string.",
                )
            )
            actions.append(
                AgentAction(
                    type=ActionType.READ_STRING,
                    arguments={"label": old_text, "max_length": max(len(old_text), len(new_text)) + 16, "wide": False},
                    reason="Read back the replacement string for verification.",
                )
            )

        if next_scan_value is not None:
            actions.append(
                AgentAction(
                    type=ActionType.NEXT_SCAN,
                    arguments={"label": label, "value": next_scan_value, "scan_type": "exact"},
                    reason="The user reported a changed value after an initial scan.",
                )
            )
            current_value = None
            target_value = None

        if current_value is not None:
            actions.append(
                AgentAction(
                    type=ActionType.SCAN_EXACT_VALUE,
                    arguments={"label": label, "value": current_value},
                    reason="The request provides a current numeric value to scan.",
                )
            )

        if target_value is not None:
            actions.append(
                AgentAction(
                    type=ActionType.WRITE_VALUE,
                    arguments={"label": label, "value": target_value},
                    reason="The request asks to modify a value.",
                )
            )

        if self._asks_for_base_address(message):
            actions.append(
                AgentAction(
                    type=ActionType.PRINT_BASE_ADDRESS,
                    arguments={"label": label},
                    reason="The request asks to print a base address.",
                )
            )

        aob_pattern = self._extract_aob_pattern(message)
        if aob_pattern:
            actions.append(
                AgentAction(
                    type=ActionType.SCAN_AOB,
                    arguments={"pattern": aob_pattern},
                    reason="The request contains an array-of-bytes pattern.",
                )
            )

        if self._looks_like_control_flow_overwrite(message):
            actions.append(
                AgentAction(
                    type=ActionType.UNSUPPORTED,
                    arguments={"category": "control_flow_overwrite"},
                    reason="The requested operation is outside the supported action set.",
                )
            )

        if not actions:
            actions.append(
                AgentAction(
                    type=ActionType.EXPLAIN,
                    arguments={
                        "text": self._explain_text(message)
                    },
                    reason="No executable memory-tool action was detected.",
                )
            )

        return AgentPlan.create(
            original_message=message,
            actions=actions,
            summary=f"Planned {len(actions)} action(s) from the request.",
        )

    @staticmethod
    def _extract_process_name(message: str) -> str | None:
        lower_message = message.lower()
        alias_match = RuleBasedPlanner._normalize_process_alias(lower_message)
        if alias_match:
            return alias_match

        patterns = [
            r"(?:打开|连接|附加到|attach)\s*([A-Za-z0-9_.\-\u4e00-\u9fff]+)",
            r"(?:玩|运行)\s*([A-Za-z0-9_.\-\u4e00-\u9fff]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                value = match.group(1).strip("，。,. ")
                if value and value not in {"现在", "当前"}:
                    return RuleBasedPlanner._normalize_process_alias(value) or value
        return None

    @staticmethod
    def _normalize_process_alias(value: str) -> str | None:
        lower_value = value.lower()
        aliases = {
            "植物大战僵尸": "PlantsVsZombies",
            "pvz": "PlantsVsZombies",
            "plants vs zombies": "PlantsVsZombies",
            "plantsvszombies": "PlantsVsZombies",
            "记事本": "notepad.exe",
            "notepad": "notepad.exe",
        }
        for alias, process in aliases.items():
            if alias in lower_value:
                return process
        return None

    @staticmethod
    def _session_action(message: str) -> AgentAction | None:
        lower_message = message.lower()
        reset_keywords = ["重新开始", "重置会话", "清空会话", "清除扫描", "重新扫描", "reset session", "clear session"]
        status_keywords = ["当前状态", "扫描状态", "会话状态", "进行到哪", "卡在哪", "session status"]

        if any(keyword in lower_message for keyword in reset_keywords):
            return AgentAction(
                type=ActionType.RESET_SESSION,
                arguments={},
                reason="The user wants to reset CheatPilot's saved scan session.",
            )
        if any(keyword in lower_message for keyword in status_keywords):
            return AgentAction(
                type=ActionType.SESSION_STATUS,
                arguments={"label": RuleBasedPlanner._extract_label(message)},
                reason="The user asks for the current CheatPilot scan session status.",
            )
        return None

    @staticmethod
    def _extract_label(message: str) -> str:
        label_candidates = ["阳光", "金币", "血量", "生命", "分数", "hp", "health", "score"]
        lower_message = message.lower()
        for label in label_candidates:
            if label.lower() in lower_message:
                return label

        generic_patterns = [
            r"(?:现在|当前|目前)\s*([A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]{0,16})\s*(?:是|为|=)\s*-?\d+",
            r"[把将]\s*([A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]{0,16})\s*(?:从\s*-?\d+\s*)?(?:改成|修改成|设置成|设为|写入|变成)",
            r"([A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]{0,16})\s*(?:改成|修改成|设置成|设为|写入|变成)\s*-?\d+",
        ]
        ignored = {"值", "数值", "当前值", "现在", "当前", "目前", "进程", "程序", "游戏", "目标"}
        for pattern in generic_patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                label = match.group(1).strip("，。,. 的")
                if label and label not in ignored:
                    return label
        return "value"

    @staticmethod
    def _extract_current_value(message: str) -> int | None:
        patterns = [
            r"(?:从|原来|原始)\s*(-?\d+)\s*(?:改成|修改成|变成|到)",
            r"(?:现在|当前|目前)?[^0-9\-]{0,8}(?:是|为|=)\s*(-?\d+)",
            r"(?:value|current)\s*(?:is|=|:)\s*(-?\d+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _extract_string_change(message: str) -> tuple[str, str] | None:
        quoted_patterns = [
            r"[把将]\s*[\"'“”‘’]([^\"'“”‘’]+)[\"'“”‘’]\s*(?:改成|修改成|替换成|变成)\s*[\"'“”‘’]([^\"'“”‘’]+)[\"'“”‘’]",
            r"(?:replace|change)\s+[\"']([^\"']+)[\"']\s+(?:with|to)\s+[\"']([^\"']+)[\"']",
        ]
        for pattern in quoted_patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return match.group(1), match.group(2)

        plain_patterns = [
            r"[把将]\s*([A-Za-z0-9_.:\-]{4,})\s*(?:改成|修改成|替换成|变成)\s*([A-Za-z0-9_.:\-]{4,})",
        ]
        for pattern in plain_patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return match.group(1), match.group(2)
        return None

    @staticmethod
    def _extract_next_scan_value(message: str) -> int | None:
        lower_message = message.lower()
        has_initial_context = any(token in lower_message for token in ["打开", "连接", "附加到", "attach", "玩", "运行"])
        patterns = [
            r"(?:继续|过滤|下一次|next\s*scan)[^0-9\-]{0,12}(-?\d+)",
            r"(?:变成|变为|变到|变化为|改为)\s*(-?\d+)",
            r"(?:现在|当前|目前)\s*(?:阳光|金币|血量|生命|分数|hp|health|score)?\s*(?:是|为|=)?\s*(-?\d+)\s*(?:了)?$",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if not match:
                continue
            if pattern.startswith("(?:现在") and has_initial_context:
                continue
            return int(match.group(1))
        return None

    @staticmethod
    def _extract_target_value(message: str) -> int | None:
        patterns = [
            r"(?:改成|修改成|设置成|设为|写入|变成|=)\s*(-?\d+)",
            r"(?:改到|调到|变到|到)\s*(-?\d+)",
            r"\b(?:set|write|change)\b\D+(-?\d+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _asks_for_base_address(message: str) -> bool:
        return "基址" in message or "base address" in message.lower()

    @staticmethod
    def _extract_aob_pattern(message: str) -> str | None:
        match = re.search(r"((?:[0-9A-Fa-f?]{2}\s+){2,}[0-9A-Fa-f?]{2})", message)
        if not match:
            return None
        return " ".join(match.group(1).split())

    @staticmethod
    def _looks_like_control_flow_overwrite(message: str) -> bool:
        keywords = ["返回地址", "return address", "retaddr", "rip", "eip", "shellcode"]
        lower_message = message.lower()
        return any(keyword in lower_message for keyword in keywords)

    @staticmethod
    def _prohibited_category(message: str) -> str | None:
        lower_message = message.lower()
        checks = [
            ("license_bypass", ["绕过注册码", "破解注册码", "注册码校验", "license bypass", "crack license"]),
            ("secret_extraction", ["会话密钥", "加密密钥", "提取密钥", "session key", "private key", "credential"]),
            ("control_flow_overwrite", ["返回地址", "return address", "retaddr", "shellcode"]),
        ]
        for category, keywords in checks:
            if any(keyword in lower_message for keyword in keywords):
                return category
        return None

    @staticmethod
    def _explain_text(message: str) -> str:
        lower_message = message.lower().strip()
        greeting_tokens = ["你好", "您好", "hello", "hi", "hey"]
        if any(token in lower_message for token in greeting_tokens):
            return (
                "你好，我是 CheatPilot。你可以直接说："
                "打开某个进程，当前某个数值是多少，帮我改成多少，并打印基址。"
            )
        return (
            "我可以用自然语言规划内存修改动作：附加进程、扫描当前数值、"
            "根据你报告的新数值继续过滤、写入目标值，并打印地址/基址。"
        )


class OpenAICompatiblePlanner:
    """Planner for OpenAI-compatible chat-completions endpoints.

    This class uses only the Python standard library so the core agent does not
    depend on a specific SDK. The model must return JSON matching the schema
    described in `_system_prompt`.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("CHEATPILOT_LLM_BASE_URL") or "").rstrip("/")
        self.api_key = api_key or os.getenv("CHEATPILOT_LLM_API_KEY") or ""
        self.model = model or os.getenv("CHEATPILOT_LLM_MODEL") or "gpt-4.1-mini"
        self.timeout_seconds = timeout_seconds

    def plan(self, message: str) -> AgentPlan:
        session_action = RuleBasedPlanner._session_action(message)
        if session_action:
            return AgentPlan.create(
                original_message=message,
                actions=[session_action],
                summary="Planned 1 session action.",
            )

        prohibited_category = RuleBasedPlanner._prohibited_category(message)
        if prohibited_category:
            return AgentPlan.create(
                original_message=message,
                actions=[
                    AgentAction(
                        type=ActionType.UNSUPPORTED,
                        arguments={"category": prohibited_category},
                        reason="The request is outside CheatPilot's supported action set.",
                    )
                ],
                summary="The request was classified as unsupported.",
            )

        if not self.base_url or not self.api_key:
            raise RuntimeError("CHEATPILOT_LLM_BASE_URL and CHEATPILOT_LLM_API_KEY are required")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": message},
            ],
            "temperature": 0,
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM planner request failed: {exc}") from exc

        content = response_data["choices"][0]["message"]["content"]
        plan_data = self._parse_json_content(content)
        actions = []
        for item in plan_data.get("actions", []):
            raw_type = str(item.get("type", "unsupported"))
            try:
                action_type = ActionType(raw_type)
                arguments = dict(item.get("arguments", {}))
            except ValueError:
                action_type = ActionType.UNSUPPORTED
                arguments = {"category": "unknown_model_action", "raw_type": raw_type}
            if action_type == ActionType.ATTACH_PROCESS:
                process = RuleBasedPlanner._normalize_process_alias(str(arguments.get("process") or ""))
                if process:
                    arguments["process"] = process
            actions.append(
                AgentAction(
                    type=action_type,
                    arguments=arguments,
                    reason=str(item.get("reason", "")),
                )
            )
        if not actions:
            actions = [
                AgentAction(
                    type=ActionType.EXPLAIN,
                    arguments={"text": "The model returned no executable actions."},
                    reason="Empty model plan.",
                )
            ]

        return AgentPlan.create(
            original_message=message,
            actions=actions,
            summary=str(plan_data.get("summary", f"Planned {len(actions)} action(s).")),
        )

    @staticmethod
    def _parse_json_content(content: str) -> dict:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
            text = re.sub(r"```$", "", text).strip()
        try:
            return dict(json.loads(text))
        except JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                return dict(json.loads(text[start : end + 1]))
            raise

    @staticmethod
    def _system_prompt() -> str:
        allowed_types = ", ".join(action.value for action in ActionType)
        return (
            "You are the planner for CheatPilot, an agent that uses Cheat Engine MCP for "
            "authorized process memory inspection and value modification. Convert the user "
            "request into JSON only. "
            "Return an object with keys summary and actions. actions is an array of objects "
            "with keys type, arguments, and reason. Allowed type values: "
            f"{allowed_types}. Use only these actions. Do not invent tool names. "
            "For numeric scans use scan_exact_value with arguments label, value, and optional value_type. "
            "If the user reports a changed value after an initial scan, use next_scan with "
            "scan_type exact and the reported value instead of scan_exact_value. "
            "For writes use write_value with label or address, value, and optional value_type. "
            "For string replacement, first use scan_string with label, value, and wide, then "
            "write_string with the same label and the replacement value, then read_string for verification. "
            "For Cheat Engine attachment use attach_process with process. "
            "Use process PlantsVsZombies when the user mentions PVZ or 植物大战僵尸. "
            "For AOB patterns use scan_aob with pattern. "
            "If the user asks to reset or clear the current CheatPilot scan session, use reset_session. "
            "If the user asks for current scan/session status, use session_status with optional label. "
            "For Lua snippets use evaluate_lua only for benign Cheat Engine automation. "
            "If the user asks for credential/key extraction, license bypass, stealth, persistence, "
            "or control-flow overwrite, return one unsupported action with a category."
        )


class HybridPlanner:
    """Rule-first planner with LLM fallback for broad natural-language phrasing."""

    def __init__(self, llm_planner: OpenAICompatiblePlanner | None = None) -> None:
        self.rule_planner = RuleBasedPlanner()
        self.llm_planner = llm_planner or OpenAICompatiblePlanner()

    def plan(self, message: str) -> AgentPlan:
        local_plan = self.rule_planner.plan(message)
        if self._should_use_local_plan(local_plan):
            return local_plan

        try:
            llm_plan = self.llm_planner.plan(message)
        except Exception as exc:
            return AgentPlan.create(
                original_message=message,
                actions=[
                    AgentAction(
                        type=ActionType.EXPLAIN,
                        arguments={
                            "text": (
                                f"LLM planner 暂时不可用：{exc}。"
                                "我仍然可以处理明确的内存修改句式，例如："
                                "打开 notepad.exe，当前分数是100，帮我改成99999，并打印基址。"
                            )
                        },
                        reason="LLM fallback failed; returning local guidance.",
                    )
                ],
                summary="LLM planner unavailable; returned local guidance.",
            )
        if self._should_use_local_plan(llm_plan):
            return llm_plan
        return local_plan

    @staticmethod
    def _should_use_local_plan(plan: AgentPlan) -> bool:
        if not plan.actions:
            return False
        if len(plan.actions) == 1 and plan.actions[0].type == ActionType.EXPLAIN:
            return _looks_like_plain_chat(plan.original_message)
        return True


def _looks_like_plain_chat(message: str) -> bool:
    lower_message = message.lower().strip()
    plain_tokens = ["你好", "您好", "hello", "hi", "hey", "介绍", "能做什么", "帮助", "help"]
    return any(token in lower_message for token in plain_tokens)
