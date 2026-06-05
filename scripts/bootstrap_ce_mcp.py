from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = Path(r"D:\MCP\cheatengine-mcp-bridge\MCP_Server")
RUNTIME_DIR = ROOT / "runtime" / "ce_mcp"
CHEAT_ENGINE_AUTORUN = Path(r"C:\Program Files\Cheat Engine\autorun")
DEFAULT_PIPE_NAME = "CE_MCP_Bridge_CheatPilot"


def build_runtime(pipe_name: str) -> tuple[Path, Path]:
    if not SOURCE_DIR.exists():
        raise FileNotFoundError(f"source MCP server directory not found: {SOURCE_DIR}")

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    lua_source = SOURCE_DIR / "ce_mcp_bridge.lua"
    py_source = SOURCE_DIR / "mcp_cheatengine.py"
    lua_target = RUNTIME_DIR / "ce_mcp_bridge.lua"
    py_target = RUNTIME_DIR / "mcp_cheatengine.py"

    lua_text = lua_source.read_text(encoding="utf-8")
    lua_text = lua_text.replace('local PIPE_NAME = "CE_MCP_Bridge_v99"', f'local PIPE_NAME = "{pipe_name}"')
    lua_target.write_text(lua_text, encoding="utf-8")

    py_text = py_source.read_text(encoding="utf-8")
    py_text = py_text.replace(
        r'PIPE_NAME = r"\\.\pipe\CE_MCP_Bridge_v99"',
        rf'PIPE_NAME = r"\\.\pipe\{pipe_name}"',
    )
    py_target.write_text(py_text, encoding="utf-8")

    requirements_source = SOURCE_DIR / "requirements.txt"
    if requirements_source.exists():
        shutil.copy2(requirements_source, RUNTIME_DIR / "requirements.txt")

    return lua_target, py_target


def install_autoload(lua_path: Path) -> Path:
    if not CHEAT_ENGINE_AUTORUN.exists():
        raise FileNotFoundError(f"Cheat Engine autorun directory not found: {CHEAT_ENGINE_AUTORUN}")

    autoload_path = CHEAT_ENGINE_AUTORUN / "cheatpilot_mcp_autoload.lua"
    autoload = f"""local bridgePath = [[{lua_path}]]

if not io.open(bridgePath, "r") then
  print("[CheatPilot MCP] Bridge script not found: " .. bridgePath)
  return
end

local ok, err = pcall(dofile, bridgePath)
if not ok then
  print("[CheatPilot MCP] Failed to autoload bridge: " .. tostring(err))
end
"""
    autoload_path.write_text(autoload, encoding="utf-8")
    return autoload_path


def update_env(py_target: Path) -> None:
    env_path = ROOT / ".env"
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    replacements = {
        "CHEATPILOT_MCP_COMMAND": r"D:\MCP\cheatengine-mcp-bridge\.venv\Scripts\python.exe",
        "CHEATPILOT_MCP_ARGS": str(py_target),
    }
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        if "=" not in line or line.strip().startswith("#"):
            output.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in replacements:
            output.append(f"{key}={replacements[key]}")
            seen.add(key)
        else:
            output.append(line)

    for key, value in replacements.items():
        if key not in seen:
            output.append(f"{key}={value}")

    env_path.write_text("\n".join(output) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build CheatPilot's dedicated Cheat Engine MCP runtime.")
    parser.add_argument("--pipe-name", default=DEFAULT_PIPE_NAME)
    parser.add_argument("--no-autoload", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    lua_target, py_target = build_runtime(args.pipe_name)
    update_env(py_target)

    print(f"Built CheatPilot CE bridge: {lua_target}")
    print(f"Built CheatPilot MCP server: {py_target}")
    print(f"Pipe name: {args.pipe_name}")

    if not args.no_autoload:
        autoload_path = install_autoload(lua_target)
        print(f"Installed Cheat Engine autoload: {autoload_path}")

    print("Restart Cheat Engine or execute the generated Lua bridge once inside Cheat Engine.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
