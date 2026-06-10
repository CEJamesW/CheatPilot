<div align="center">

# CheatPilot

### 由 LLM 驱动的实时内存修改 Agent

用自然语言对话，让 AI 理解目标、规划工具调用，并通过 Cheat Engine MCP 执行真实的进程附加、内存扫描、候选筛选、数值写入和地址输出。

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![LLM](https://img.shields.io/badge/LLM-tool--calling-111827?style=flat-square)
![Backend](https://img.shields.io/badge/Backend-Cheat%20Engine%20MCP-ef4444?style=flat-square)

</div>

---

## 项目简介

CheatPilot 是一个通用的自然语言内存修改 Agent。用户不需要手写扫描流程，只需要描述目标程序、当前可见数值和期望结果；Agent 会将对话交给 LLM，由模型决定何时调用工具、何时要求用户补充信息、何时继续缩小候选地址，并把执行交给真实的 Cheat Engine MCP 后端。

项目当前提供三种入口：

- CLI：适合命令行和多轮交互
- API：适合接入 Web、桌面端或其他 Agent 系统
- 桌面 UI：适合直接以聊天窗口操作

## 核心能力

- 自然语言对话式控制
- OpenAI-compatible Chat Completions tool calling
- Cheat Engine MCP 真实后端执行
- 目标进程附加与进程校验
- 精确数值扫描与 next scan 筛选
- 多轮扫描会话状态保存
- 唯一候选地址写入与读回确认
- 地址 / 基址信息输出
- 本地文件、进程和命令工具调用
- CLI、API、桌面 UI 三种入口

## 工作流程

```text
用户输入
  -> LLM Agent
  -> 工具调用计划
  -> CheatPilot Executor
  -> Cheat Engine MCP
  -> Cheat Engine Lua Bridge
  -> 目标进程内存
```

典型对话流程：

```text
user> 附加到 game.exe
assistant> 已附加到目标进程。你想修改哪个数值？

user> 当前金币是 150，帮我改成 9999，并打印地址
assistant> 扫描到多个候选地址。请让金币变化一次，然后告诉我变化后的新值。

user> 现在金币是 120
assistant> 已继续筛选。如果候选仍不唯一，会继续要求你改变数值；唯一后会写入并读回确认。
```

## 目录结构

```text
cheatpilot/
  tool_agent.py              LLM tool-use Agent
  executors/ce_mcp.py        Cheat Engine MCP 执行器
  executors/local_tools.py   本地文件、进程和命令工具
  mcp_client.py              MCP stdio 客户端
  api.py                     FastAPI 服务入口
  ui.py                      桌面聊天窗口
runtime/ce_mcp/              项目内置 Cheat Engine MCP 运行文件
scripts/                     启动、检查和初始化脚本
tests/                       回归测试
vendor/                      vendored Cheat Engine MCP Bridge
```

## 环境要求

- Python 3.11 或更高版本
- Cheat Engine
- Cheat Engine MCP Bridge
- 支持 Chat Completions 和 tool calling 的 OpenAI-compatible LLM 服务

## 安装

```bash
pip install -e .
```

初始化项目内置 Cheat Engine MCP 运行环境：

```powershell
python scripts\bootstrap_ce_mcp.py
```

如果不希望写入 Cheat Engine autorun，可以使用：

```powershell
python scripts\bootstrap_ce_mcp.py --no-autoload
```

## 配置

复制配置模板：

```powershell
Copy-Item .env.example .env
```

`.env` 可填写项：

```bash
# LLM 服务地址。填写 OpenAI-compatible API base URL。
# 示例：https://api.openai.com/v1
CHEATPILOT_LLM_BASE_URL=

# LLM API Key。不要提交真实密钥。
CHEATPILOT_LLM_API_KEY=

# 支持 chat/completions 和 tool calling 的模型名称。
CHEATPILOT_LLM_MODEL=

# LLM 单次请求超时时间，单位为秒。
CHEATPILOT_LLM_TIMEOUT_SECONDS=45

# LLM 遇到 429、超时等临时错误时的最大重试次数。
CHEATPILOT_LLM_MAX_RETRIES=8

# 单轮用户请求内，Agent 最多允许模型连续调用多少轮工具。
CHEATPILOT_MAX_TOOL_ROUNDS=10

# 保留给 LLM 的历史对话消息数量。
CHEATPILOT_MAX_HISTORY_MESSAGES=24

# Agent 规划模式。推荐使用 llm。
# 可选：llm、tool、tooluse、hybrid、openai、rule
CHEATPILOT_PLANNER=llm

# Cheat Engine MCP Server 的 Python 可执行文件路径。
# 可填写 python、虚拟环境 python，或完整 python.exe 路径。
CHEATPILOT_MCP_COMMAND=python

# Cheat Engine MCP Server 脚本路径。
# 通常使用项目内置 runtime\ce_mcp\mcp_cheatengine.py。
CHEATPILOT_MCP_ARGS=runtime\ce_mcp\mcp_cheatengine.py

# MCP 单次工具调用超时时间，单位为秒。
CHEATPILOT_MCP_TIMEOUT_SECONDS=60

# 是否允许 LLM 直接触发额外 Lua 动作。
# 可选：0、1
CHEATPILOT_ALLOW_LUA=1

# 默认数值类型。
# 可选：byte、word、dword、qword、float、double
CHEATPILOT_VALUE_TYPE=dword

# 单次扫描最多保留 / 展示的候选地址数量。
CHEATPILOT_MAX_SCAN_RESULTS=25
```

## 运行

CLI 单次指令：

```powershell
python -m cheatpilot "附加到 game.exe，当前金币是 150，帮我改成 9999，并打印地址"
```

CLI 多轮交互：

```powershell
python -m cheatpilot -i
```

桌面 UI：

```powershell
.\scripts\start_ui.ps1
```

API：

```powershell
.\scripts\start_api.ps1
```

健康检查：

```powershell
python scripts\check_mcp.py
python scripts\check_llm_tooluse.py
```

## API 示例

启动 API 后，可以向 `/chat` 发送自然语言请求：

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d "{\"message\":\"当前金币是 150，帮我改成 9999\"}"
```

多会话场景可以传入 `session_id`：

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"demo\",\"message\":\"现在金币是 120\"}"
```

## 使用方式

用户可以用自然语言描述：

- 要附加的目标程序
- 当前可见数值
- 期望修改后的数值
- 是否需要输出地址信息
- 数值变化后的新值

当扫描结果不唯一时，Agent 会要求用户在目标程序中改变该数值，并继续报告变化后的新值。系统会通过多轮扫描逐步缩小候选地址，直到满足写入条件；写入后会尝试读回确认结果。

## 测试

```powershell
python -m unittest discover -s tests -v
```

## 项目状态

当前版本已实现：

- LLM tool-use Agent
- Cheat Engine MCP 执行后端
- 多轮扫描状态管理
- CLI / API / UI 入口
- 本地文件、进程、命令工具
- 基础回归测试覆盖
