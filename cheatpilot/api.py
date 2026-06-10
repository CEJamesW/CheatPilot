from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from cheatpilot.config import PROJECT_ROOT
from cheatpilot.errors import user_facing_error
from cheatpilot.factory import build_agent
from cheatpilot.formatter import format_response
from cheatpilot.models import ActionResult, ActionType, AgentAction, AgentResponse


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None
    takeover_ce_session: bool = False


class ChatResponse(BaseModel):
    ok: bool
    reply: str
    session_id: str
    ce_session_owner: str | None = None
    plan: dict
    results: list[dict]


app = FastAPI(title="CheatPilot", version="0.1.0")
_session_lock = threading.RLock()
_agents: dict[str, Any] = {}
_ce_session_owner: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> dict:
    global _ce_session_owner
    session_id = _normalize_session_id(request.session_id)
    agent = _get_session_agent(session_id)
    try:
        with _session_lock:
            _set_agent_takeover(agent, request.takeover_ce_session)
            response = agent.handle(request.message)
            _update_ce_session_owner(session_id, response, allow_takeover=request.takeover_ce_session)
    except Exception as exc:
        return {
            "ok": False,
            "reply": user_facing_error(exc),
            "session_id": session_id,
            "ce_session_owner": _ce_session_owner,
            "plan": {},
            "results": [{"ok": False, "message": str(exc), "data": {"error": str(exc)}}],
        }
    finally:
        _close_agent_client(agent)
    payload = response.to_dict()
    payload["reply"] = format_response(response)
    payload["session_id"] = session_id
    payload["ce_session_owner"] = _ce_session_owner
    return payload


@app.get("/sessions")
def sessions() -> dict[str, Any]:
    with _session_lock:
        return {"sessions": sorted(_agents.keys()), "ce_session_owner": _ce_session_owner}


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> dict[str, Any]:
    global _ce_session_owner
    normalized = _normalize_session_id(session_id)
    with _session_lock:
        agent = _agents.pop(normalized, None)
        if agent is not None:
            _close_agent_client(agent)
        state_path = _session_state_path(normalized)
        removed_state = False
        if state_path.exists():
            state_path.unlink()
            removed_state = True
        if _ce_session_owner == normalized:
            _ce_session_owner = None
        return {
            "ok": True,
            "session_id": normalized,
            "removed_agent": agent is not None,
            "removed_state": removed_state,
            "ce_session_owner": _ce_session_owner,
        }


@app.post("/sessions/{session_id}/release-ce")
def release_ce_session(session_id: str) -> dict[str, Any]:
    global _ce_session_owner
    normalized = _normalize_session_id(session_id)
    with _session_lock:
        released = _ce_session_owner == normalized
        if released:
            _ce_session_owner = None
        return {"ok": True, "session_id": normalized, "released": released, "ce_session_owner": _ce_session_owner}


def _get_session_agent(session_id: str) -> Any:
    with _session_lock:
        agent = _agents.get(session_id)
        if agent is None:
            state_path = _session_state_path(session_id)
            agent = build_agent(state_path=state_path)
            _install_api_session_executor(agent, session_id)
            _agents[session_id] = agent
        return agent


def _session_state_path(session_id: str) -> Path:
    return PROJECT_ROOT / "runtime" / "api_sessions" / f"{session_id}.json"


def _normalize_session_id(value: str | None) -> str:
    raw = (value or "default").strip()
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "_", raw).strip("._-")
    return normalized[:80] or "default"


def _close_agent_client(agent: Any) -> None:
    close = getattr(agent, "close", None)
    if callable(close):
        close()


class _ApiSessionExecutor:
    def __init__(self, *, session_id: str, inner: Any) -> None:
        self.session_id = session_id
        self.inner = inner
        self.allow_takeover = False

    def execute(self, action: AgentAction) -> ActionResult:
        if action.type in _CE_SESSION_ACTIONS:
            with _session_lock:
                owner = _ce_session_owner
                if owner not in {None, self.session_id} and not self.allow_takeover:
                    return _ce_session_busy_action_result(action, self.session_id, owner)
        return self.inner.execute(action)

    def close(self) -> None:
        close = getattr(self.inner, "close", None)
        if callable(close):
            close()


def _install_api_session_executor(agent: Any, session_id: str) -> None:
    executor = getattr(agent, "executor", None)
    if executor is not None and not isinstance(executor, _ApiSessionExecutor):
        setattr(agent, "executor", _ApiSessionExecutor(session_id=session_id, inner=executor))


def _set_agent_takeover(agent: Any, allow_takeover: bool) -> None:
    executor = getattr(agent, "executor", None)
    if isinstance(executor, _ApiSessionExecutor):
        executor.allow_takeover = allow_takeover


def _ce_session_busy_action_result(action: AgentAction, session_id: str, owner: str) -> ActionResult:
    return ActionResult(
        action=action,
        ok=False,
        message=(
            f"CE MCP 后端当前由 session `{owner}` 占用。"
            "本次 CE 内存动作未执行；普通对话和本地工具不受影响。"
        ),
        data={
            "error": "ce_session_busy",
            "session_id": session_id,
            "owner": owner,
            "fatal": True,
            "next_step": "请使用当前占用会话继续，或在请求中设置 takeover_ce_session=true 接管后重试该内存动作。",
        },
    )


def _update_ce_session_owner(session_id: str, response: AgentResponse, *, allow_takeover: bool = False) -> None:
    global _ce_session_owner
    for result in response.results:
        action = result.action
        if action.type == ActionType.RESET_SESSION and result.ok and _ce_session_owner == session_id:
            _ce_session_owner = None
        elif action.type in _CE_SESSION_ACTIONS and result.ok and (_ce_session_owner in {None, session_id} or allow_takeover):
            _ce_session_owner = session_id


_CE_SESSION_ACTIONS = {
    ActionType.ATTACH_PROCESS,
    ActionType.GET_PROCESS_INFO,
    ActionType.SCAN_EXACT_VALUE,
    ActionType.NEXT_SCAN,
    ActionType.WRITE_VALUE,
    ActionType.PRINT_BASE_ADDRESS,
    ActionType.READ_VALUE,
    ActionType.SCAN_STRING,
    ActionType.READ_STRING,
    ActionType.SCAN_AOB,
    ActionType.WRITE_BYTES,
    ActionType.WRITE_STRING,
    ActionType.EVALUATE_LUA,
    ActionType.CE_MCP_CALL,
}
