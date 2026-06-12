from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.agent import AgentLoop
from src.agent.scheduler import Scheduler
from src.core.config import load_settings


def main() -> None:
    """Unattended daemon: python -m src.cli.schedule

    Tasks live in data/schedules.json (see data/schedules.example.json).
    Gated tools are DENIED in scheduled runs — the agent reads, researches,
    calculates, and drafts; humans action anything side-effecting.
    """
    settings = load_settings()
    config_path = settings.dir_data / "schedules.json"
    if not config_path.exists():
        print(f"No schedule config at {config_path}. Copy data/schedules.example.json to get started.")
        return
    scheduler = Scheduler.from_config(
        loop=AgentLoop(settings=settings),
        config_path=config_path,
        state_path=settings.dir_data / "schedules_state.json",
    )
    print(f"AssetOS scheduler running with {len(scheduler.tasks)} task(s). Ctrl-C to stop.")
    try:
        scheduler.run_forever()
    except KeyboardInterrupt:
        print("\nScheduler stopped.")


if __name__ == "__main__":
    main()
