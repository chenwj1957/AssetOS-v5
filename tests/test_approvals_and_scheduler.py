from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.agent import AgentLoop, ScheduledTask, Scheduler
from tests.test_agent_loop import ScriptedLLM, make_settings, seed_asset


# ---------------------------------------------------------------------------
# Approval gates
# ---------------------------------------------------------------------------

def gated_llm() -> ScriptedLLM:
    return ScriptedLLM(
        [
            {"thought": "delegate", "action": {"tool": "codex_agent", "args": {"task": "reorganise files"}}},
            {"thought": "adapt", "final_answer": "Drafted a plan instead; delegation needs approval."},
        ]
    )


def test_gated_tool_denied_by_default(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    state = AgentLoop(settings=settings, llm_client=gated_llm(), emit=lambda _: None).run("tidy up")
    assert state.turns[0].observation.startswith("DENIED")
    assert "approval" in state.turns[0].observation
    assert state.answer.startswith("Drafted a plan")


def test_gated_tool_runs_when_policy_approves(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    approvals: list[str] = []

    def approve(tool: str, args: dict) -> bool:
        approvals.append(tool)
        return True

    state = AgentLoop(
        settings=settings, llm_client=gated_llm(), emit=lambda _: None, approval_policy=approve
    ).run("tidy up")
    assert approvals == ["codex_agent"]
    assert state.turns[0].observation.startswith("AGENTIC:")


def test_ungated_tools_never_ask(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_asset(settings)
    asked: list[str] = []
    llm = ScriptedLLM(
        [
            {"thought": "read", "action": {"tool": "read_memory", "args": {"asset_id": "12_ocean_st", "files": ["lease.md"]}}},
            {"thought": "done", "final_answer": "ok"},
        ]
    )
    AgentLoop(
        settings=settings,
        llm_client=llm,
        emit=lambda _: None,
        approval_policy=lambda tool, args: asked.append(tool) or True,
    ).run("rent?")
    assert asked == []


# ---------------------------------------------------------------------------
# Schedule due-logic
# ---------------------------------------------------------------------------

def test_schedule_due_logic() -> None:
    interval = ScheduledTask("t", "x", {"type": "interval", "minutes": 60})
    now = datetime(2026, 6, 15, 10, 0)  # a Monday
    assert interval.is_due(now, None)
    assert not interval.is_due(now, datetime(2026, 6, 15, 9, 30))
    assert interval.is_due(now, datetime(2026, 6, 15, 8, 59))

    daily = ScheduledTask("t", "x", {"type": "daily", "at": "09:00"})
    assert daily.is_due(now, None)
    assert daily.is_due(now, datetime(2026, 6, 14, 9, 5))  # ran yesterday
    assert not daily.is_due(now, datetime(2026, 6, 15, 9, 5))  # already ran today
    assert not daily.is_due(datetime(2026, 6, 15, 8, 0), None)  # before anchor

    weekly = ScheduledTask("t", "x", {"type": "weekly", "day": "MO", "at": "09:00"})
    assert weekly.is_due(now, None)
    assert not weekly.is_due(datetime(2026, 6, 16, 10, 0), None)  # Tuesday
    assert not weekly.is_due(now, datetime(2026, 6, 15, 9, 1))  # already ran


# ---------------------------------------------------------------------------
# Scheduler runs, persists state, and stays gated
# ---------------------------------------------------------------------------

def test_scheduler_runs_due_tasks_once_and_persists(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_asset(settings)
    llm = ScriptedLLM(
        [
            {"thought": "scheduled work", "final_answer": "Arrears check complete: none overdue."},
        ]
    )
    fixed_now = datetime(2026, 6, 15, 9, 30)  # Monday after 09:00 anchor
    scheduler = Scheduler(
        loop=AgentLoop(settings=settings, llm_client=llm, emit=lambda _: None),
        tasks=[ScheduledTask("arrears", "Check arrears.", {"type": "weekly", "day": "MO", "at": "09:00"})],
        state_path=settings.dir_data / "schedules_state.json",
        clock=lambda: fixed_now,
    )
    results = scheduler.run_pending()
    assert len(results) == 1
    name, run_state = results[0]
    assert name == "arrears"
    assert run_state.user_task.startswith("[Scheduled task: arrears]")
    assert "unattended scheduled run" in run_state.session_context
    assert run_state.journal_path is not None  # unattended runs are auditable

    # Second poll the same morning: nothing due.
    assert scheduler.run_pending() == []
    saved = json.loads((settings.dir_data / "schedules_state.json").read_text())
    assert "arrears" in saved["last_run"]

    # A fresh scheduler (process restart) reloads state and does not double-run.
    scheduler2 = Scheduler(
        loop=AgentLoop(settings=settings, llm_client=ScriptedLLM([]), emit=lambda _: None),
        tasks=scheduler.tasks,
        state_path=settings.dir_data / "schedules_state.json",
        clock=lambda: fixed_now,
    )
    assert scheduler2.run_pending() == []


def test_scheduled_runs_deny_gated_tools(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    scheduler = Scheduler(
        loop=AgentLoop(settings=settings, llm_client=gated_llm(), emit=lambda _: None),
        tasks=[ScheduledTask("nightly", "Tidy files.", {"type": "interval", "minutes": 1})],
        state_path=settings.dir_data / "schedules_state.json",
        clock=lambda: datetime(2026, 6, 15, 3, 0),
    )
    [(_, run_state)] = scheduler.run_pending()
    assert run_state.turns[0].observation.startswith("DENIED")


def test_scheduler_from_config(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    config = settings.dir_data / "schedules.json"
    config.write_text(
        json.dumps(
            {
                "tasks": [
                    {"name": "a", "task": "do a", "schedule": {"type": "interval", "minutes": 5}},
                    {"name": "b", "task": "do b", "schedule": {"type": "daily", "at": "08:00"}, "enabled": False},
                ]
            }
        ),
        encoding="utf-8",
    )
    scheduler = Scheduler.from_config(
        loop=AgentLoop(settings=settings, llm_client=ScriptedLLM([]), emit=lambda _: None),
        config_path=config,
        state_path=settings.dir_data / "schedules_state.json",
    )
    assert [t.name for t in scheduler.tasks] == ["a", "b"]
    assert scheduler.tasks[1].enabled is False
