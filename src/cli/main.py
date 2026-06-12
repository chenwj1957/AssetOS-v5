from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.agent import AgentLoop, Session
from src.core.config import load_settings
from src.core.errors import PMIntelligenceError
from src.outputs.formatter import format_result

EXIT_COMMANDS = {"exit", "quit", "q"}


def run_once(user_task: str) -> str:
    settings = load_settings()
    state = AgentLoop(settings=settings).run(user_task)
    output = format_result(state, settings)
    print(output)
    return output


def main() -> None:
    """Perpetual session REPL.

    Each question runs a fresh inner ReAct loop seeded with the session
    summary; every run journals itself into searchable memory, so state
    compounds in memory rather than in an ever-growing context window.
    """
    settings = load_settings()

    def interactive_approval(tool_name: str, args: dict) -> bool:
        reply = input(f"\nApprove '{tool_name}' with args {args}? [y/N]: ").strip().lower()
        return reply in {"y", "yes"}

    session = Session(loop=AgentLoop(settings=settings, approval_policy=interactive_approval))
    print("AssetOS Agent — type 'exit' to quit.")
    while True:
        try:
            user_task = input("\nTask: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_task:
            continue
        if user_task.lower() in EXIT_COMMANDS:
            break
        try:
            state = session.ask(user_task)
            print(format_result(state, settings))
        except PMIntelligenceError as exc:
            print(f"AssetOS error: {exc}")
    print("Session ended. Run history is journaled in memory.")


if __name__ == "__main__":
    main()
