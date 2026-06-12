from __future__ import annotations

import json
import time as time_module
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable

from src.agent.loop import AgentLoop
from src.core.types import AgentState

WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


@dataclass(frozen=True)
class ScheduledTask:
    """A recurring task fed into the agent loop unattended.

    Schedules (no external cron dependency):
    - {"type": "interval", "minutes": N}
    - {"type": "daily",  "at": "HH:MM"}
    - {"type": "weekly", "day": "MO", "at": "HH:MM"}
    """

    name: str
    task: str
    schedule: dict[str, Any]
    enabled: bool = True

    def is_due(self, now: datetime, last_run: datetime | None) -> bool:
        kind = self.schedule.get("type")
        if kind == "interval":
            minutes = int(self.schedule["minutes"])
            return last_run is None or now - last_run >= timedelta(minutes=minutes)
        if kind == "daily":
            anchor = self._todays_anchor(now)
            return now >= anchor and (last_run is None or last_run < anchor)
        if kind == "weekly":
            day = WEEKDAYS.get(str(self.schedule.get("day", "")).upper())
            if day is None:
                raise ValueError(f"Schedule '{self.name}': unknown weekday '{self.schedule.get('day')}'.")
            if now.weekday() != day:
                return False
            anchor = self._todays_anchor(now)
            return now >= anchor and (last_run is None or last_run < anchor)
        raise ValueError(f"Schedule '{self.name}': unknown type '{kind}'.")

    def _todays_anchor(self, now: datetime) -> datetime:
        hour, minute = (int(part) for part in str(self.schedule.get("at", "09:00")).split(":"))
        return datetime.combine(now.date(), time(hour=hour, minute=minute))


class Scheduler:
    """Runs due tasks through the agent loop and persists last-run state.

    Unattended runs inherit the loop's approval policy — pass none and
    gated tools are DENIED by default, so a scheduled run can read,
    research, calculate, and draft, but never take gated actions without
    a human. Every run journals itself (see src.agent.journal), so
    unattended activity is fully auditable in memory.
    """

    def __init__(
        self,
        loop: AgentLoop,
        tasks: list[ScheduledTask],
        state_path: Path,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.loop = loop
        self.tasks = tasks
        self.state_path = state_path
        self.clock = clock

    @classmethod
    def from_config(cls, loop: AgentLoop, config_path: Path, state_path: Path) -> "Scheduler":
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        tasks = [
            ScheduledTask(
                name=str(item["name"]),
                task=str(item["task"]),
                schedule=dict(item["schedule"]),
                enabled=bool(item.get("enabled", True)),
            )
            for item in payload.get("tasks", [])
        ]
        return cls(loop=loop, tasks=tasks, state_path=state_path)

    def run_pending(self) -> list[tuple[str, AgentState]]:
        now = self.clock()
        state = self._load_state()
        results: list[tuple[str, AgentState]] = []
        for task in self.tasks:
            if not task.enabled:
                continue
            last_run = state.get(task.name)
            if not task.is_due(now, last_run):
                continue
            # Record the attempt up-front so a crashing task cannot
            # retrigger in a tight loop.
            state[task.name] = now
            self._save_state(state)
            run_state = self.loop.run(
                f"[Scheduled task: {task.name}] {task.task}",
                session_context=f"This is an unattended scheduled run at {now.isoformat(timespec='minutes')}.",
            )
            results.append((task.name, run_state))
        return results

    def run_forever(self, poll_seconds: int = 60) -> None:  # pragma: no cover - daemon loop
        while True:
            for name, run_state in self.run_pending():
                print(f"\n[scheduler] {name}: {str(run_state.answer)[:300]}")
            time_module.sleep(poll_seconds)

    # ------------------------------------------------------------------

    def _load_state(self) -> dict[str, datetime]:
        if not self.state_path.exists():
            return {}
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        return {
            name: datetime.fromisoformat(stamp)
            for name, stamp in payload.get("last_run", {}).items()
        }

    def _save_state(self, state: dict[str, datetime]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(
                {"last_run": {name: stamp.isoformat() for name, stamp in state.items()}},
                indent=2,
            ),
            encoding="utf-8",
        )
