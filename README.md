# CheatPilot：由 LLM 驱动的实时内存修改系统

CheatPilot 是一个基于自然语言对话的内存修改 Agent。用户用普通语言描述目标进程、当前数值和期望结果，系统由 LLM 规划工具调用，并通过 Cheat Engine MCP 执行进程附加、内存扫描、结果筛选、数值写入和地址输出等操作。

本项目面向课程设计、实验演示和受控环境下的自动化内存分析研究。

## 项目目标

用自然语言对话，让 AI 自动完成实时内存修改流程。

典型流程包括：

1. 用户描述目标程序和当前数值。
2. LLM 判断意图并选择工具。
3. CheatPilot 调用 Cheat Engine MCP 附加目标进程。
4. 系统扫描当前数值并保存候选地址。
5. 如果候选地址不唯一，Agent 引导用户改变数值并继续筛选。
6. 找到唯一地址后写入目标值，并返回执行结果和地址信息。

## 核心能力

- 自然语言对话式控制
- LLM tool calling 工具规划
- Cheat Engine MCP 后端执行
- 进程附加与校验
- 精确数值扫描与 next scan 筛选
- 多轮扫描会话状态保存
- 唯一候选地址写入
- 地址/基址信息输出
- CLI、API、桌面 UI 三种入口

## 系统架构

```text
用户输入
  -> LLM Agent
  -> 工具调用计划
  -> CheatPilot Executor
  -> Cheat Engine MCP
  -> Cheat Engine Lua Bridge
  -> 目标进程内存
```

主要模块：

- `cheatpilot/tool_agent.py`：LLM tool-use Agent
- `cheatpilot/executors/ce_mcp.py`：Cheat Engine MCP 执行器
- `cheatpilot/mcp_client.py`：MCP stdio 客户端
- `cheatpilot/api.py`：FastAPI 服务入口
- `cheatpilot/ui.py`：桌面聊天窗口
- `runtime/ce_mcp/`：项目内置 Cheat Engine MCP 运行文件
- `scripts/`：启动、检查和初始化脚本

## 环境要求

- Python 3.11 或更高版本
- Cheat Engine
- Cheat Engine MCP Bridge
- 支持 OpenAI-compatible Chat Completions 和 tool calling 的 LLM 服务

## 安装

```powershell
pip install -e .
```

初始化 Cheat Engine MCP 运行环境：

```powershell
python scripts\bootstrap_ce_mcp.py
```

## 配置

复制 `.env.example` 为 `.env`，并填写实际配置：

```text
CHEATPILOT_LLM_BASE_URL=
CHEATPILOT_LLM_API_KEY=
CHEATPILOT_LLM_MODEL=
CHEATPILOT_PLANNER=llm
CHEATPILOT_MCP_COMMAND=
CHEATPILOT_MCP_ARGS=
```

常用可选配置：

```text
CHEATPILOT_LLM_TIMEOUT_SECONDS=
CHEATPILOT_LLM_MAX_RETRIES=
CHEATPILOT_VALUE_TYPE=
CHEATPILOT_MAX_SCAN_RESULTS=
CHEATPILOT_ALLOW_LUA=
```

`.env` 包含私密密钥，不应提交到仓库。

## 运行

CLI：

```powershell
python -m cheatpilot "你的自然语言指令"
```

桌面 UI：

```powershell
.\scripts\start_ui.ps1
```

API：

```powershell
.\scripts\start_api.ps1
```

健康检查和 MCP 检查：

```powershell
python scripts\check_mcp.py
python scripts\check_llm_tooluse.py
```

## 使用方式

用户可以用自然语言描述：

- 要附加的目标程序
- 当前可见数值
- 期望修改后的数值
- 是否需要输出地址信息
- 数值变化后的新值

当扫描结果不唯一时，Agent 会要求用户在目标程序中改变该数值，并继续报告变化后的新值。系统会使用多轮扫描逐步缩小候选地址，直到满足写入条件。

## 安全边界

CheatPilot 仅用于用户授权的本地实验、课程演示和受控测试环境。项目不应被用于未授权软件修改、凭据或密钥提取、授权绕过、持久化控制、隐蔽访问、控制流劫持或其他破坏性行为。

默认产品路径聚焦于数值型内存扫描与写入。高风险能力应在受控实验环境中单独审查和显式开启。

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
- 基础测试覆盖

后续可扩展方向：

- 更稳定的指针链分析
- 更细粒度的写入保护
- 更完整的桌面交互体验
- 更多可观测日志与审计记录
