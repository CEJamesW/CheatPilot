# CheatPilot：由 LLM 驱动的实时内存修改系统

> 用自然语言对话，让 AI 自动修改内存。

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![LLM](https://img.shields.io/badge/LLM-tool--calling-111827?style=flat-square)
![Backend](https://img.shields.io/badge/Backend-Cheat%20Engine%20MCP-ef4444?style=flat-square)

CheatPilot 是一个基于自然语言对话的内存修改 Agent。用户用普通语言描述目标进程、当前数值和期望结果，系统由 LLM 规划工具调用，并通过 Cheat Engine MCP 执行进程附加、内存扫描、结果筛选、数值写入和地址输出等操作。

* * *

## 信息

| 项目 | 内容 |
| --- | --- |
| 目标 | 用自然语言对话，让 AI 自动修改内存 |
| 依赖 | Cheat Engine MCP（`C:\Program Files\Cheat Engine`） |

| 场景  | 用户输入                                                     |
| ----- | ------------------------------------------------------------ |
| 场景1 | 某软件会校验注册码是否正确，否则无法使用。帮我打开软件并绕过注册码校验 |
| 场景2 | 我在玩植物大战僵尸，现在的阳光是 100 。帮我把阳光修改成 99999 ，并打印出阳光基址 |
| 场景3 | 找到并打印出某系统当前 TCP 连接的加密会话密钥                |
| 场景4 | 向某进程的 input 缓冲区写入 A 字符，自动计算偏移并覆盖函数返回地址为 0x12345678 |

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

## 架构

```text
用户输入
  -> LLM Agent
  -> 工具调用计划
  -> CheatPilot Executor
  -> Cheat Engine MCP
  -> Cheat Engine Lua Bridge
  -> 目标进程内存
```

## 目录

```text
cheatpilot/
  tool_agent.py              LLM tool-use Agent
  executors/ce_mcp.py        Cheat Engine MCP 执行器
  mcp_client.py              MCP stdio 客户端
  api.py                     FastAPI 服务入口
  ui.py                      桌面聊天窗口
runtime/ce_mcp/              项目内置 Cheat Engine MCP 运行文件
scripts/                     启动、检查和初始化脚本
```

## 环境要求

- Python 3.11 或更高版本
- Cheat Engine
- Cheat Engine MCP Bridge
- 支持 OpenAI-compatible Chat Completions 和 tool calling 的 LLM 服务

## 安装

    pip install -e .

初始化 Cheat Engine MCP 运行环境：

    python scripts\bootstrap_ce_mcp.py

## 配置

复制 `.env.example` 为 `.env`，并填写实际配置：

```env
# 示例：https://api.openai.com/v1
CHEATPILOT_LLM_BASE_URL=

CHEATPILOT_LLM_API_KEY=

# 要选择支持 chat/completions 和 tool calling 的模型。
CHEATPILOT_LLM_MODEL=

# Agent 规划模式。
# 推荐：llm
# 可选：llm、tool、tooluse、hybrid、openai、rule
CHEATPILOT_PLANNER=llm

# Cheat Engine MCP Server 的 Python 可执行文件路径，必须填写。
# 可填写系统 python、虚拟环境 python，或其他能运行 MCP Server 的 Python 路径。
# Windows 示例：D:\MCP\cheatengine-mcp-bridge\.venv\Scripts\python.exe
CHEATPILOT_MCP_COMMAND=

# Cheat Engine MCP Server 脚本路径，必须填写。
# 通常指向 runtime/ce_mcp/mcp_cheatengine.py 或 vendor 中的 MCP Server 脚本。
CHEATPILOT_MCP_ARGS=

# LLM 单次请求超时时间，单位为秒。
# 可选，默认建议：45
CHEATPILOT_LLM_TIMEOUT_SECONDS=45

# LLM 遇到 429、超时等临时错误时的最大重试次数。
# 可选，默认建议：8
CHEATPILOT_LLM_MAX_RETRIES=8

# 默认数值类型。
# 可选：byte、word、dword、qword、float、double
CHEATPILOT_VALUE_TYPE=dword

# 单次扫描最多保留/展示的候选地址数量。
# 可选，默认建议：25
CHEATPILOT_MAX_SCAN_RESULTS=25

# 是否允许 LLM 直接触发额外 Lua 动作。
# 可选：0、1
CHEATPILOT_ALLOW_LUA=0
```

## 运行

CLI：

    python -m cheatpilot "你的自然语言指令"

桌面 UI：

    .\scripts\start_ui.ps1

API：

    .\scripts\start_api.ps1

健康检查和 MCP 检查：

    python scripts\check_mcp.py
    python scripts\check_llm_tooluse.py

## 使用方式

用户可以用自然语言描述：

- 要附加的目标程序
- 当前可见数值
- 期望修改后的数值
- 是否需要输出地址信息
- 数值变化后的新值

当扫描结果不唯一时，Agent 会要求用户在目标程序中改变该数值，并继续报告变化后的新值。系统会使用多轮扫描逐步缩小候选地址，直到满足写入条件。

## 测试

    python -m unittest discover -s tests -v

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
