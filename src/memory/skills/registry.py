from __future__ import annotations

import json
from pathlib import Path

from src.core.config import Settings


class SkillRegistry:
    def __init__(self, settings: Settings, skills_dir: Path | None = None) -> None:
        self.settings = settings
        self.skills_dir = skills_dir or self.settings.dir_skills

    def list_skill_names(self) -> list[str]:
        if not self.skills_dir.exists():
            return []
        return sorted(
            path.name
            for path in self.skills_dir.iterdir()
            if path.is_dir() and (path / "skill.md").is_file()
        )

    def list_skill_summaries(self, max_chars: int = 700) -> dict[str, str]:
        summaries: dict[str, str] = {}
        for skill_name in self.list_skill_names():
            text = self.skill_summary(skill_name)
            summaries[skill_name] = text[:max_chars]
        return summaries

    def list_available_skills(self, max_chars: int = 700) -> list[dict[str, str]]:
        return [
            {"name": name, "summary": summary}
            for name, summary in self.list_skill_summaries(max_chars=max_chars).items()
        ]

    def resolve_skill_path(self, skill_name: str) -> Path:
        clean_name = Path(skill_name).name
        return self.skills_dir / clean_name / "skill.md"

    def skill_summary(self, skill_name: str) -> str:
        metadata_path = self.skills_dir / Path(skill_name).name / "skill.json"
        if metadata_path.exists() and metadata_path.is_file():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            summary = metadata.get("summary")
            if isinstance(summary, str) and summary.strip():
                return " ".join(summary.split())
        path = self.resolve_skill_path(skill_name)
        return " ".join(path.read_text(encoding="utf-8").split())
