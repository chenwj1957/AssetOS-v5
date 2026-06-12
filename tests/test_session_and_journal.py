from __future__ import annotations

from pathlib import Path

from src.agent import AgentLoop, Session
from src.memory.assets import AssetRegistry
from src.memory.search import MemoryIndex
from tests.test_agent_loop import ScriptedLLM, make_settings, seed_asset


def make_loop(settings, llm) -> AgentLoop:
    return AgentLoop(settings=settings, llm_client=llm, emit=lambda _: None)


# ---------------------------------------------------------------------------
# End-of-run reflection (journal)
# ---------------------------------------------------------------------------

def test_run_journal_written_under_active_asset(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_asset(settings)
    llm = ScriptedLLM(
        [
            {"thought": "read", "action": {"tool": "read_memory", "args": {"asset_id": "12_ocean_st", "files": ["lease.md"]}}},
            {"thought": "done", "final_answer": "Rent is $1000/week."},
        ]
    )
    state = make_loop(settings, llm).run("What is the rent?")
    assert state.journal_path is not None
    assert state.journal_path.parent == settings.dir_assets / "12_ocean_st" / "runs"
    content = state.journal_path.read_text(encoding="utf-8")
    assert "Task: What is the rent?" in content
    assert "read_memory" in content
    assert "Rent is $1000/week." in content


def test_run_journal_written_globally_without_asset_and_on_limit(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    llm = ScriptedLLM([{"thought": "loop", "action": {"tool": "list_skills", "args": {}}}] * 10)
    state = make_loop(settings, llm).run("never finishes")
    assert state.journal_path is not None  # journaled even on iteration-limit exit
    assert state.journal_path.parent == settings.dir_data / "memory" / "runs"
    assert "iteration limit" in state.journal_path.read_text(encoding="utf-8")


def test_journals_are_searchable(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_asset(settings)
    llm = ScriptedLLM(
        [
            {"thought": "read", "action": {"tool": "read_memory", "args": {"asset_id": "12_ocean_st", "files": ["lease.md"]}}},
            {"thought": "done", "final_answer": "Drafted the strata levy memorandum for the owner."},
        ]
    )
    make_loop(settings, llm).run("Prepare strata levy memorandum")
    index = MemoryIndex(
        db_path=settings.dir_data / "memory" / "index.sqlite3",
        asset_registry=AssetRegistry(settings=settings),
        global_runs_dir=settings.dir_data / "memory" / "runs",
    )
    hits = index.search("strata levy memorandum")
    assert hits and hits[0].asset_id == "12_ocean_st"
    assert hits[0].file_name.startswith("runs/")
    index.close()


# ---------------------------------------------------------------------------
# Session continuity
# ---------------------------------------------------------------------------

def test_session_carries_context_and_active_asset(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_asset(settings)
    llm = ScriptedLLM(
        [
            # Run 1
            {"thought": "read", "action": {"tool": "read_memory", "args": {"asset_id": "12_ocean_st", "files": ["lease.md"]}}},
            {"thought": "done", "final_answer": "Weekly rent is $1000."},
            # Run 2 (follow-up)
            {"thought": "compute", "action": {"tool": "calculate", "args": {"expression": "round(1000 * 52 / 12, 2)"}}},
            {"thought": "done", "final_answer": "Monthly rent is $4333.33."},
        ]
    )
    session = Session(loop=make_loop(settings, llm))
    first = session.ask("What is the weekly rent at 12 Ocean St?")
    assert first.answer == "Weekly rent is $1000."
    assert session.active_asset == "12_ocean_st"

    second = session.ask("And monthly?")
    # The second run's controller prompts must include the session summary.
    run2_prompts = [p for p in llm.prompts if "And monthly?" in p]
    assert run2_prompts
    assert all("Weekly rent is $1000." in p for p in run2_prompts)
    assert all("Active asset from earlier in this session: 12_ocean_st" in p for p in run2_prompts)
    assert second.answer == "Monthly rent is $4333.33."


def test_session_context_is_capped(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    session = Session(loop=make_loop(settings, ScriptedLLM([])))
    session.exchanges = [(f"question {i}", "x" * 400) for i in range(30)]
    context = session._render_context()
    assert len(context) <= 4_200  # cap plus trim marker
    assert "question 29" in context  # newest kept
    assert "[earlier exchanges trimmed]" in context
