from __future__ import annotations

import argparse
import json

from cheatpilot.errors import user_facing_error
from cheatpilot.factory import build_agent
from cheatpilot.formatter import format_response


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the CheatPilot agent.")
    parser.add_argument("message", nargs="*", help="Natural-language instruction.")
    parser.add_argument("--json", action="store_true", help="Print the full JSON result.")
    parser.add_argument("-i", "--interactive", action="store_true", help="Start a multi-turn chat session.")
    parser.add_argument("--planner", choices=["llm", "tool", "tooluse", "hybrid", "openai", "rule"], help="Planner backend.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    message = " ".join(args.message).strip()

    agent = build_agent(planner_name=args.planner)
    try:
        if args.interactive or not message:
            _run_interactive(agent, json_output=args.json)
            return

        try:
            response = agent.handle(message)
        except Exception as exc:
            if args.json:
                print(json.dumps({"ok": False, "reply": user_facing_error(exc), "error": str(exc)}, ensure_ascii=False, indent=2))
            else:
                print(user_facing_error(exc))
            raise SystemExit(1) from None

        if args.json:
            print(json.dumps(response.to_dict(), ensure_ascii=False, indent=2))
            return

        print(format_response(response, include_json_hint=True))
    finally:
        agent.close()


def _run_interactive(agent, *, json_output: bool = False) -> None:
    print("CheatPilot interactive. Type exit, quit, or q to stop.")
    while True:
        try:
            message = input("user> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not message:
            continue
        if message.lower() in {"exit", "quit", "q", "退出"}:
            return

        try:
            response = agent.handle(message)
        except Exception as exc:
            if json_output:
                print(json.dumps({"ok": False, "reply": user_facing_error(exc), "error": str(exc)}, ensure_ascii=False, indent=2))
            else:
                print(f"assistant> {user_facing_error(exc)}")
            continue

        if json_output:
            print(json.dumps(response.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"assistant> {format_response(response)}")


if __name__ == "__main__":
    main()
