from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


##################### Memory items (used by src.memory) #####################

@dataclass(frozen=True)
class Skill:
    name: str
    path: Path
    content: str
    summary: str = ""


@dataclass(frozen=True)
class File:
    asset_id: str
    file_name: str
    path: Path
    summary: str = ""
    content: str = ""


##################### Agent run state #####################

@dataclass(frozen=True)
class ArtifactResult:
    artifact_type: str
    path: Path
    metadata_path: Path | None = None


@dataclass(frozen=True)
class EventLog:
    timestamp: datetime
    event_details: dict[str, Any]


@dataclass
class AgentTurn:
    """One observe-think-act cycle in the loop."""
    iteration: int
    thought: str
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    observation: str = ""


@dataclass
class AgentState:
    user_task: str
    session_context: str = ""
    turns: list[AgentTurn] = field(default_factory=list)
    event_log: list[EventLog] = field(default_factory=list)
    answer: str = ""
    artifacts: list[ArtifactResult] = field(default_factory=list)
    # Scratch shared between tools across iterations (e.g. invoice JSON
    # produced by generate_invoice and consumed by build_docx).
    selected_asset: str | None = None
    last_structured_result: dict[str, Any] | None = None
    journal_path: Path | None = None
