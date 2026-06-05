# CheatPilot

**CheatPilot: LLM-driven real-time memory modification system**

CheatPilot turns natural-language requests into real Cheat Engine MCP actions. The main product path is:

```text
User message -> LLM tool calls -> CheatPilot tools -> Cheat Engine MCP -> Cheat Engine Lua bridge -> target process
```

There is no mock executor in product code. CLI, API, and the desktop window all use the dedicated Cheat Engine MCP runtime in this project.

## Main Workflow

Start from a sentence that names the target process, current value, desired value, and optional address output:

```text
打开 game.exe，当前金币是150，帮我改成99999，并打印基址
```

CheatPilot will:

1. Attach Cheat Engine to the target process.
2. Scan the current value as a `dword`.
3. If there are multiple candidates, save the pending write and base-address request.
4. Ask you to change that value in the target program.
5. When you reply with the new value, for example `现在金币是50了`, run `next_scan`.
6. Once there is one candidate left, write `99999`, read it back, and print the address/base address.

PVZ is just a real test target:

```text
我在玩植物大战僵尸，现在的阳光是150。帮我把阳光修改成99999，并打印出阳光基址
```

Useful follow-up commands:

```text
现在阳光是50了
查看阳光扫描状态
重新开始
```

## First Run

Bootstrap the dedicated CheatPilot MCP runtime:

```powershell
cd C:\Users\Administrator\Desktop\CheatPilot
python scripts\bootstrap_ce_mcp.py
```

Then start or restart Cheat Engine. The bootstrap installs:

```text
C:\Program Files\Cheat Engine\autorun\cheatpilot_mcp_autoload.lua
```

If Cheat Engine is already open, run this once inside Cheat Engine:

```lua
dofile([[C:\Users\Administrator\Desktop\CheatPilot\runtime\ce_mcp\ce_mcp_bridge.lua]])
```

## Run CLI

Default LLM tool-use agent:

```powershell
python -m cheatpilot "我在玩植物大战僵尸，现在的阳光是100。帮我把阳光修改成99999，并打印出阳光基址"
python -m cheatpilot "hook植物大战僵尸"
python -m cheatpilot "现在阳光是50了"
python -m cheatpilot "查看阳光扫描状态"
python -m cheatpilot "打开 game.exe，当前金币是150，帮我改成99999，并打印基址"
```

Short PVZ helper:

```powershell
.\scripts\cheatpilot_pvz.ps1
.\scripts\cheatpilot_pvz.ps1 "现在阳光是50了"
```

Deterministic rule planner:

```powershell
python -m cheatpilot --planner rule "我在玩植物大战僵尸，现在的阳光是100。帮我把阳光修改成99999，并打印出阳光基址"
```

Machine-readable output:

```powershell
python -m cheatpilot --json "查看阳光扫描状态"
```

## Run Desktop Window

```powershell
.\scripts\start_ui.ps1
```

The desktop window is a topmost chat surface with no shortcut/action buttons. Every message you type is sent to the LLM first; the LLM then decides whether to answer directly or call CheatPilot tools backed by Cheat Engine MCP.

## Run API

```powershell
.\scripts\start_api.ps1
```

Call the chat endpoint:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/chat -ContentType 'application/json' -Body '{"message":"查看阳光扫描状态"}'
```

API responses include:

- `reply`: compact user-facing text.
- `plan`: structured actions.
- `results`: raw action data from CheatPilot and Cheat Engine MCP.

## MCP Check

```powershell
python scripts\check_mcp.py
```

Expected bridge-level success:

```json
{
  "success": true,
  "message": "CE MCP Bridge v11.4.0 alive"
}
```

`No process attached` is normal until Cheat Engine attaches to a target process.

## Configuration

Runtime config lives in `.env`:

```text
CHEATPILOT_LLM_BASE_URL=https://ai.saurlax.com/v1
CHEATPILOT_LLM_API_KEY=...
CHEATPILOT_LLM_MODEL=mimo-v2.5-pro
CHEATPILOT_LLM_TIMEOUT_SECONDS=45
CHEATPILOT_LLM_MAX_RETRIES=8
CHEATPILOT_PLANNER=llm
CHEATPILOT_MCP_COMMAND=D:\MCP\cheatengine-mcp-bridge\.venv\Scripts\python.exe
CHEATPILOT_MCP_ARGS=C:\Users\Administrator\Desktop\CheatPilot\runtime\ce_mcp\mcp_cheatengine.py
CHEATPILOT_ALLOW_LUA=0
CHEATPILOT_VALUE_TYPE=dword
CHEATPILOT_MAX_SCAN_RESULTS=25
```

`CHEATPILOT_PLANNER=llm` is the default OpenAI-compatible tool-use agent. Every user message is sent to the model configured by `CHEATPILOT_LLM_MODEL` first. The agent sends tool schemas to the model, executes returned `tool_calls`, feeds tool results back to the model, and displays the model's final reply. Retryable LLM failures such as HTTP 429 are retried inside the same LLM request according to `CHEATPILOT_LLM_MAX_RETRIES`, so Cheat Engine tool actions are not repeated just because the model's final wording was rate-limited. Use `CHEATPILOT_PLANNER=hybrid` for the older local-rule-first JSON planner, `openai` for raw JSON planning, or `rule` for deterministic local parsing.

Check whether the configured LLM supports tool calls:

```powershell
python scripts\check_llm_tooluse.py
```

The configured endpoint has been verified to return OpenAI-compatible `tool_calls`.

`CHEATPILOT_ALLOW_LUA=0` disables model-generated Lua actions. CheatPilot's internal process attach still uses controlled Cheat Engine MCP Lua automation.

## Open-Source Base

The project is structured so the tool-use layer can be moved onto an open-source agent base later:

- `mcp-use`: closest match when the goal is to connect any LLM to MCP servers and run tool-access agents.
- OpenAI Agents SDK: good fit if the runtime standardizes on OpenAI-compatible tool/function calling.
- `smolagents`: lightweight, but code-first agents are less predictable for this memory-modification workflow.
- LangGraph: powerful for complex graphs, but heavier than this first product needs.

Current implementation keeps a small local hybrid planner plus a Cheat Engine MCP executor. That gives stable PVZ/notepad/live-process behavior now while keeping the tool boundary narrow enough to replace with an open-source framework later.

## Session State

CheatPilot saves scan state in:

```text
C:\Users\Administrator\Desktop\CheatPilot\runtime\session_state.json
```

This file lets the agent continue a scan across multiple user messages. Use `重新开始` to clear it before a fresh run.

## Tests

Planner and local behavior tests:

```powershell
python -m unittest discover -s tests -v
```

Real execution is validated separately with `scripts\check_mcp.py` and live Cheat Engine MCP calls.

## Key Files

- `cheatpilot/planner.py`: LLM and deterministic rule planners.
- `cheatpilot/tool_agent.py`: OpenAI-compatible LLM tool-use agent.
- `cheatpilot/agent.py`: natural-language request orchestration.
- `cheatpilot/executors/ce_mcp.py`: real Cheat Engine MCP executor.
- `cheatpilot/formatter.py`: shared CLI/API/UI reply formatting.
- `cheatpilot/api.py`: FastAPI service.
- `cheatpilot/ui.py`: topmost desktop chat window.
- `runtime/ce_mcp/mcp_cheatengine.py`: dedicated MCP server.
- `runtime/ce_mcp/ce_mcp_bridge.lua`: dedicated Cheat Engine Lua bridge.
- `AGENT.md`: live project progress notes.
