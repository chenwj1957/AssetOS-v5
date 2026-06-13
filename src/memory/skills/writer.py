from __future__ import annotations

import json
import re
from pathlib import Path

from src.core.errors import UnsafeMemoryPathError
from src.memory.paths import resolve_within
from src.memory.skills.registry import SkillRegistry


class SkillWriter:
    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def create_skill(self, name: str, content: str, summary: str | None = None) -> Path:
        skill_id = self.slugify_skill_name(name)
        skill_dir = resolve_within(self.registry.skills_dir, skill_id, label=f"Skill path '{skill_id}'")
        if skill_dir.exists():
            raise UnsafeMemoryPathError(f"Skill already exists: {skill_id}")
        skill_dir.mkdir(parents=True, exist_ok=False)
        (skill_dir / "skill.md").write_text(content, encoding="utf-8")
        if summary and summary.strip():
            (skill_dir / "skill.json").write_text(
                json.dumps({"summary": summary.strip()}, indent=2), encoding="utf-8"
            )
        return skill_dir

    @staticmethod
    def slugify_skill_name(value: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9]+", "_", value.strip())
        slug = re.sub(r"_+", "_", slug).strip("_")
        if not slug:
            raise ValueError("Skill name must contain at least one letter or number.")
        return slug
