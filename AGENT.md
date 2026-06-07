# CheatPilot Agent Progress

Project: CheatPilot: LLM-driven real-time memory modification system

## Current Goal

Deliver a complete first product version before another live test pass.

Target user flow:

```text
打开任意目标进程，当前某个数值是150，帮我改成99999，并打印基址
```

The agent should attach to a real process through Cheat Engine MCP, scan the current value, guide the user through value changes when candidates are not unique, write the target value after a unique candidate is found, and print the address/base address. PVZ is only the current live test target.

## Status

- [x] Project folder created under `C:\Users\Administrator\Desktop\CheatPilot`.
- [x] Project name fixed: CheatPilot: LLM-driven real-time memory modification system.
- [x] Product execution path is Cheat Engine MCP only.
- [x] Mock executor removed from product code.
- [x] Dedicated CheatPilot CE MCP runtime generated.
- [x] Dedicated pipe name set to `CE_MCP_Bridge_CheatPilot`.
- [x] Cheat Engine autoload installed.
- [x] LLM planner configured for the OpenAI-compatible endpoint/model in `.env`.
- [x] Deterministic rule planner kept for local reproducibility.
- [x] LLM tool-use agent added as default `CHEATPILOT_PLANNER=llm`.
- [x] Hybrid planner retained as optional local-rule-first JSON planner.
- [x] Normal chat like `你好` now goes to the LLM first.
- [x] UI shortcut buttons removed; the desktop window is a pure chat surface.
- [x] UI now shows a non-chat `思考中...` status while waiting for the LLM/tool loop.
- [x] LLM HTTP request layer waits longer and retries after HTTP 429 without repeating already executed Cheat Engine tool actions.
- [x] Tool-use agent no longer runs local rule shortcuts before the LLM.
- [x] Tool results are fed back to the LLM and the UI/API/CLI display the model's final reply.
- [x] LLM timeout increased to 45 seconds for the configured endpoint/model.
- [x] Retryable LLM failures, including HTTP 429, now retry automatically up to `CHEATPILOT_LLM_MAX_RETRIES` before surfacing an error.
- [x] LLM prompt now treats `hook/attach/connect/打开/连接/附加到` as attach-process intent.
- [x] CLI/API/UI now report LLM failures explicitly instead of falling back to local rule responses.
- [x] CLI entry point implemented.
- [x] FastAPI entry point implemented.
- [x] Topmost desktop chat window implemented.
- [x] Shared user-facing response formatter added.
- [x] PVZ alias handling added: `植物大战僵尸` and `PVZ` map to `PlantsVsZombies`.
- [x] Multi-turn scan state persists in `runtime/session_state.json`.
- [x] Candidate-too-many behavior saves pending write and pending base-address print.
- [x] Follow-up messages like `现在阳光是50了` run `next_scan`.
- [x] Session status action added.
- [x] Reset session action added.
- [x] README rewritten as a product usage manual.
- [x] Generic labels supported beyond PVZ sun, for example `金币`, `血量`, `分数`, or custom labels parsed from the request.
- [x] Open-source base options documented; current version keeps a lightweight tool loop with a replaceable planner boundary.
- [x] Configured endpoint verified to return OpenAI-compatible `tool_calls`.
- [x] Attach validation added so a failed/mismatched `openProcess` cannot keep scanning the previous attached process.
- [x] Agent stops the plan immediately after attach failure to avoid scanning/writing the wrong process.
- [x] Tool-use loop expanded with a `think` tool so the LLM can expose concise operational state before non-trivial actions.
- [x] Local project tools added for the agent: `list_files`, `read_file`, `write_file`, and `run_command`.
- [x] Composite executor added so local tools route locally while all memory operations still route to Cheat Engine MCP.
- [x] Raw `ce_mcp_call` added for direct real Cheat Engine MCP tool calls when high-level tools are not enough.
- [x] LLM prompt revised toward an observe-think-act agent loop instead of a fixed workflow.
- [x] Scan label continuity improved for generic value labels and omitted-label follow-up turns.
- [x] README restyled to match the requested concise Chinese project style while preserving the existing information.
- [x] Tool observations sent back to the LLM are now compacted so large raw MCP/file/command outputs do not overload the next model turn.
- [x] Numeric writes now require Cheat Engine MCP write success plus readback confirmation before CheatPilot claims the write succeeded.
- [x] Default MCP command now uses the current Python interpreter plus the vendored `runtime/ce_mcp/mcp_cheatengine.py`, with `.env` still able to override it.
- [x] Bootstrap and autoload scripts now target the vendored CheatPilot MCP runtime instead of a developer-specific `D:\MCP` source path.
- [x] MCP check now fails early with clear local path/dependency guidance when Python or the MCP server script is missing.
- [x] Project dependencies now include the MCP SDK and Windows pipe dependency needed by the vendored CE MCP server.
- [x] MCP stdio calls now have a real request timeout and stderr diagnostics so a stuck Cheat Engine bridge cannot leave the UI waiting forever.
- [x] Tool-use arguments are now validated before execution so malformed LLM tool-call JSON is returned as a tool observation instead of crashing the chat.
- [x] One Agent instance now serializes full chat turns to protect LLM history, CE scan state, and `runtime/session_state.json` from concurrent UI/API requests.
- [x] Desktop UI now blocks duplicate sends while a request is already thinking.
- [x] If final LLM summarization fails after real tool results were produced, CheatPilot now returns the real last tool result and next step instead of dropping the plan.
- [x] Stale MCP stdio clients are discarded after timeout/pipe/stdout failures so the next turn can reconnect cleanly.
- [x] `run_command` now supports selectable `powershell`, `pwsh`, `cmd`, `bash`, and `sh` shells while keeping PowerShell as the default.
- [x] High-level numeric tools now accept integer, float, and string numeric values; `float`/`double` value types are preserved across scan/write/readback.
- [x] The vendored Cheat Engine MCP wrapper now exposes `write_integer` as `int | float`, matching the Lua bridge's real float/double support.

## Live Results So Far

- Notepad memory write test succeeded through Cheat Engine MCP.
- PVZ process was found as `PlantsVsZombies`.
- A previous PVZ live scan/write pass reached unique address `0x211BC5B0` and wrote/read `99999`.
- The latest user-reported value `现在阳光是50了` was processed, but the current Cheat Engine scan pool still had many matches, so CheatPilot correctly kept the pending write and asked for another value change instead of writing blindly.
- A generic `game.exe` validation command exposed stale-process behavior in Cheat Engine attachment; this is now guarded by process/module validation. The temporary fake session state was removed.
- Lightweight live LLM check `python -m cheatpilot "你好"` succeeded and returned an LLM-generated reply without touching Cheat Engine.

## Current Product Behavior

CheatPilot is now a tool-use agent loop rather than a fixed scripted workflow:

1. The LLM receives every user message first.
2. The LLM uses `think` for concise operational state when the task is non-trivial.
3. The LLM asks the user for missing facts such as the current visible value instead of guessing.
4. High-level memory tools execute through real Cheat Engine MCP and preserve scan session state.
5. Raw `ce_mcp_call` can call real Cheat Engine MCP tools for low-level inspection when needed.
6. Local tools let the agent inspect project files or run commands without leaving the same tool loop.

For ordinary numeric memory changes, the expected agent behavior is:

1. Attach to the named target process through Cheat Engine MCP when needed.
2. If the user did not provide the current value, ask for it.
3. Scan the current value with a stable label.
4. Observe candidate count from the real MCP result.
5. If candidates are not unique, ask the user to change the same value and report the new value.
6. Continue narrowing with `next_scan`.
7. Write and read back only when the tool result identifies a usable address.
8. Claim success only after the write result and readback confirm the requested value.

## Useful Commands

```powershell
cd C:\Users\Administrator\Desktop\CheatPilot
python scripts\check_llm_tooluse.py
python -m cheatpilot "我在玩植物大战僵尸，现在的阳光是100。帮我把阳光修改成99999，并打印出阳光基址"
python -m cheatpilot "打开 game.exe，当前金币是150，帮我改成99999，并打印基址"
python -m cheatpilot "现在阳光是50了"
python -m cheatpilot "查看阳光扫描状态"
python -m cheatpilot "重新开始"
.\scripts\start_ui.ps1
.\scripts\start_api.ps1
```

## Testing Note

User instruction: pause live testing for now and first complete the project. No further PVZ/CE live test should be run until the user asks to test again.

## Next Step

Run a final verification pass when the user is ready:

```powershell
python -m unittest discover -s tests -v
python scripts\check_mcp.py
```
