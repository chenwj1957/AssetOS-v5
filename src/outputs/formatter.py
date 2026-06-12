from __future__ import annotations

from pathlib import Path

from src.core.config import Settings
from src.core.types import AgentState


def format_result(state: AgentState, settings: Settings) -> str:
    tool_trace = "\n".join(
        f"  {turn.iteration}. {turn.tool or '(format retry)'}"
        for turn in state.turns
    ) or "  - none"
    artifacts = "\n".join(
        f"  - {a.artifact_type}: {_display_path(a.path, settings)}"
        for a in state.artifacts
    ) or "  - none"
    return (
        "==================== AssetOS result ====================\n"
        f"Task: {state.user_task}\n"
        f"Active asset: {state.selected_asset or 'none'}\n"
        f"Tool trace:\n{tool_trace}\n"
        f"Artifacts:\n{artifacts}\n"
        "Answer:\n"
        f"{state.answer}\n"
    )


def _display_path(path: Path, settings: Settings) -> str:
    for base in (settings.project_root, settings.dir_data):
        try:
            return str(path.resolve().relative_to(base.resolve()))
        except ValueError:
            continue
    return str(path)
