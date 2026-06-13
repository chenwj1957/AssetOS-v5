from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Any, Callable

from src.core.config import Settings
from src.core.types import AgentState, ArtifactResult
from src.llm.client import LLMClient
from src.memory.assets import AssetRegistry, AssetWriter
from src.memory.facts import FactReader, FactWriter, SchemaRegistry
from src.memory.search import MemoryIndex
from src.memory.files.reader import FileReader
from src.memory.files.registry import FileRegistry
from src.memory.files.writer import FileWriter
from src.memory.skills import SkillReader, SkillRegistry


@dataclass
class MemoryHub:
    """All memory-layer collaborators a tool may need, wired once by the agent."""
    asset_registry: AssetRegistry
    asset_writer: AssetWriter
    file_registry: FileRegistry
    file_reader: FileReader
    file_writer: FileWriter
    skill_registry: SkillRegistry
    skill_reader: SkillReader
    schema_registry: SchemaRegistry
    fact_reader: FactReader
    fact_writer: FactWriter
    memory_index: MemoryIndex


@dataclass
class ToolContext:
    """Everything a tool may need, wired once by the agent."""
    settings: Settings
    llm_client: LLMClient
    memory: MemoryHub
    state: AgentState


@dataclass
class ToolResult:
    """What a tool returns to the loop.

    ``observation`` is fed back to the agent verbatim (truncated).
    ``artifact`` is surfaced to the user at the end of the run.
    ``structured`` is stashed in state for downstream tools
    (e.g. invoice JSON consumed by build_docx).
    """
    observation: str
    artifact: ArtifactResult | None = None
    structured: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args: dict[str, str]  # arg name -> human-readable description
    run: Callable[[ToolContext, dict[str, Any]], ToolResult]
    # Side-effecting tools (writes outside drafts, sends, payments,
    # delegated computer use) pause for human approval before running.
    requires_approval: bool = False

    def schema_line(self) -> str:
        arg_text = ", ".join(f"{name}: {desc}" for name, desc in self.args.items()) or "no args"
        return f"- {self.name}({arg_text})\n  {self.description}"


def require_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Tool argument '{key}' must be a non-empty string.")
    return value.strip()


def catches(*exc_types: type[Exception]) -> Callable[[Callable[..., ToolResult]], Callable[..., ToolResult]]:
    """Wrap a tool's ``run`` function so the listed exceptions become an
    ``ERROR: ...`` observation instead of failing the agent loop."""

    def decorator(fn: Callable[..., ToolResult]) -> Callable[..., ToolResult]:
        @functools.wraps(fn)
        def wrapper(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
            try:
                return fn(ctx, args)
            except exc_types as exc:
                return ToolResult(observation=f"ERROR: {exc}")

        return wrapper

    return decorator
