from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel, Field

from cheatpilot.errors import user_facing_error
from cheatpilot.factory import build_agent
from cheatpilot.formatter import format_response


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    ok: bool
    reply: str
    plan: dict
    results: list[dict]


app = FastAPI(title="CheatPilot", version="0.1.0")
agent = build_agent()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> dict:
    try:
        response = agent.handle(request.message)
    except Exception as exc:
        return {
            "ok": False,
            "reply": user_facing_error(exc),
            "plan": {},
            "results": [{"ok": False, "message": str(exc), "data": {"error": str(exc)}}],
        }
    payload = response.to_dict()
    payload["reply"] = format_response(response)
    return payload
