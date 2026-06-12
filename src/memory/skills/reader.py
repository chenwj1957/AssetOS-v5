from __future__ import annotations

from src.core.errors import SkillNotFoundError
from src.core.types import Skill
from src.memory.skills.registry import SkillRegistry


class SkillReader:
    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def read_skill(self, skill_name: str) -> Skill:
        path = self.registry.resolve_skill_path(skill_name)
        if not path.exists() or not path.is_file():
            available = ", ".join(self.registry.list_skill_names()) or "none"
            raise SkillNotFoundError(
                f"Selected skill '{skill_name}' was not found at {path}. Available skills: {available}."
            )
        return Skill(
            name=path.parent.name,
            path=path,
            content=path.read_text(encoding="utf-8"),
            summary=self.registry.skill_summary(path.parent.name),
        )

    def read_skills(self, skill_names: list[str]) -> list[Skill]:
        return [self.read_skill(name) for name in skill_names]
