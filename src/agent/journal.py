from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from src.core.config import Settings
from src.core.types import AgentState

GLOBAL_RUNS_DIR_NAME = "runs"
ANSWER_EXCERPT_CHARS = 1_500
OBSERVATION_EXCERPT_CHARS = 160
MEMORY_WRITE_TOOLS = {"save_memory_note", "create_asset", "evolve_schema", "extract_facts"}


def write_run_journal(state: AgentState, settings: Settings) -> Path | None:
    """Persist a deterministic summary of a completed run into memory.

    Episodic memory: every run leaves a searchable trace, so future runs
    (and future sessions) can recall what was asked, what was done, and
    what came of it. Asset-scoped runs land in the asset's ``runs/``
    folder (picked up by the FTS index automatically); asset-less runs
    land in ``data/memory/runs/``.

    Deliberately mechanical — no LLM call — so journaling is free,
    reliable, and cannot itself fail a run.
    """
    if not state.turns and not state.answer:
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if state.selected_asset:
        base = settings.dir_assets / state.selected_asset / "runs"
    else:
        base = settings.dir_data / "memory" / GLOBAL_RUNS_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{timestamp}_run.md"
    if path.exists():  # same-second collision
        path = base / f"{timestamp}_{len(state.turns)}_run.md"

    memory_touched = sorted({t.tool for t in state.turns if t.tool in MEMORY_WRITE_TOOLS})
    lines = [
        f"# Run {timestamp}",
        "",
        f"Task: {state.user_task}",
        f"Active asset: {state.selected_asset or 'none'}",
        "",
        "## Actions",
    ]
    for turn in state.turns:
        if not turn.tool:
            continue
        excerpt = _one_line(turn.observation, OBSERVATION_EXCERPT_CHARS)
        lines.append(f"- {turn.iteration}. {turn.tool}: {excerpt}")
    if not any(turn.tool for turn in state.turns):
        lines.append("- (answered directly from context)")

    if state.artifacts:
        lines += ["", "## Artifacts"]
        lines += [f"- {a.artifact_type}: {a.path}" for a in state.artifacts]

    if memory_touched:
        lines += [
            "",
            f"Memory-writing tools used: {', '.join(memory_touched)}. "
            "If markdown changed, facts may be flagged STALE — re-run extract_facts when next queried.",
        ]

    lines += ["", "## Outcome", _excerpt(state.answer, ANSWER_EXCERPT_CHARS)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _one_line(text: str, limit: int) -> str:
    flattened = " ".join(text.split())
    return flattened[:limit] + ("…" if len(flattened) > limit else "")


def _excerpt(text: str, limit: int) -> str:
    cleaned = re.sub(r"\n{3,}", "\n\n", text.strip())
    return cleaned[:limit] + ("…" if len(cleaned) > limit else "")
