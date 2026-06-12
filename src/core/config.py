from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.core.constants import (
    DEFAULT_CODEX_AGENT_SANDBOX,
    DEFAULT_CODEX_AGENT_TIMEOUT_SECONDS,
    DEFAULT_CODEX_MODEL,
    DEFAULT_DIR_ASSETS,
    DEFAULT_DIR_DATA,
    DEFAULT_DIR_SKILLS,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MEMORY_FILE_MAX_BYTES,
    DEFAULT_MEMORY_FILES_MAX,
    DEFAULT_OBSERVATION_MAX_CHARS,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_URL,
    DEFAULT_RENDERED_CONTEXT_MAX_CHARS,
    DEFAULT_TRANSCRIPT_MAX_CHARS,
)


@dataclass(frozen=True)
class Settings:
    project_root: Path
    dir_data: Path
    dir_skills: Path
    dir_assets: Path
    ollama_url: str
    ollama_model: str
    codex_model: str
    memory_file_max_bytes: int = DEFAULT_MEMORY_FILE_MAX_BYTES
    memory_file_max_number: int = DEFAULT_MEMORY_FILES_MAX
    context_max_chars: int = DEFAULT_RENDERED_CONTEXT_MAX_CHARS
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    observation_max_chars: int = DEFAULT_OBSERVATION_MAX_CHARS
    transcript_max_chars: int = DEFAULT_TRANSCRIPT_MAX_CHARS
    codex_agent_timeout_seconds: int = DEFAULT_CODEX_AGENT_TIMEOUT_SECONDS
    codex_agent_sandbox: str = DEFAULT_CODEX_AGENT_SANDBOX


def load_settings(project_root: Path | None = None) -> Settings:
    root = project_root or Path(__file__).resolve().parents[2]

    dir_data = Path(DEFAULT_DIR_DATA)
    if not dir_data.is_absolute():
        dir_data = root / dir_data

    return Settings(
        project_root=root,
        dir_data=dir_data,
        dir_skills=dir_data / DEFAULT_DIR_SKILLS,
        dir_assets=dir_data / DEFAULT_DIR_ASSETS,
        ollama_url=DEFAULT_OLLAMA_URL.rstrip("/"),
        ollama_model=DEFAULT_OLLAMA_MODEL,
        codex_model=DEFAULT_CODEX_MODEL,
    )
