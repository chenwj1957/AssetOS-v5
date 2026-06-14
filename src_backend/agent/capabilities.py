from __future__ import annotations

import json
from pathlib import Path


class CapabilitiesStore:
    """Persists which tools/skills are disabled.

    Shared application state: any entry point (web UI, CLI, scheduler) can
    read or change this and have the agent loop respect it consistently.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.disabled_tools: set[str] = set()
        self.disabled_skills: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.disabled_tools = set(data.get("disabled_tools", []))
        self.disabled_skills = set(data.get("disabled_skills", []))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "disabled_tools": sorted(self.disabled_tools),
                    "disabled_skills": sorted(self.disabled_skills),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def tool_enabled(self, tool_name: str) -> bool:
        return tool_name not in self.disabled_tools

    def skill_enabled(self, skill_name: str) -> bool:
        return skill_name not in self.disabled_skills

    def set_tool_enabled(self, tool_name: str, enabled: bool) -> None:
        if enabled:
            self.disabled_tools.discard(tool_name)
        else:
            self.disabled_tools.add(tool_name)
        self.save()

    def set_skill_enabled(self, skill_name: str, enabled: bool) -> None:
        if enabled:
            self.disabled_skills.discard(skill_name)
        else:
            self.disabled_skills.add(skill_name)
        self.save()
