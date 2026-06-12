from pathlib import Path

import pytest

from src.core.config import Settings
from src.core.errors import SkillNotFoundError
from src.memory.skills import SkillReader
from src.memory.skills import SkillRegistry


def make_settings(tmp_path: Path, skills_dir: Path | None = None) -> Settings:
    return Settings(
        project_root=tmp_path,
        dir_data=tmp_path,
        dir_skills=skills_dir or tmp_path / "skills",
        dir_assets=tmp_path / "assets",
        ollama_url="",
        ollama_model="",
        codex_model="",
    )


def test_skill_reader_reads_markdown_skill(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "commercial_property_manager"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.md").write_text("Skill body", encoding="utf-8")

    skill = SkillReader(SkillRegistry(settings=make_settings(tmp_path, skills_dir))).read_skill("commercial_property_manager")

    assert skill.name == "commercial_property_manager"
    assert skill.path == skill_dir / "skill.md"
    assert skill.content == "Skill body"
    assert skill.summary == "Skill body"


def test_skill_registry_lists_directory_skills_with_skill_markdown(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    (skills_dir / "commercial_property_manager").mkdir(parents=True)
    (skills_dir / "commercial_property_manager" / "skill.md").write_text("Skill body", encoding="utf-8")
    (skills_dir / "draft_skill.md").write_text("Old flat layout", encoding="utf-8")
    (skills_dir / "incomplete_skill").mkdir()

    assert SkillRegistry(settings=make_settings(tmp_path, skills_dir)).list_skill_names() == ["commercial_property_manager"]


def test_skill_registry_lists_skill_summaries(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "accounts_manager"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.md").write_text("Generate rent invoices and track arrears.", encoding="utf-8")

    summaries = SkillRegistry(settings=make_settings(tmp_path, skills_dir)).list_skill_summaries(max_chars=21)

    assert summaries == {"accounts_manager": "Generate rent invoice"}


def test_skill_registry_lists_available_skills_with_summaries(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "accounts_manager"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.md").write_text("Generate rent invoices and track arrears.", encoding="utf-8")

    available_skills = SkillRegistry(settings=make_settings(tmp_path, skills_dir)).list_available_skills(max_chars=21)

    assert available_skills == [{"name": "accounts_manager", "summary": "Generate rent invoice"}]


def test_skill_registry_prefers_skill_json_summary(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "accounts_manager"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.md").write_text("Long skill body", encoding="utf-8")
    (skill_dir / "skill.json").write_text(
        '{"summary": "Rent invoices, GST, arrears, and receivables."}',
        encoding="utf-8",
    )

    summaries = SkillRegistry(settings=make_settings(tmp_path, skills_dir)).list_skill_summaries()

    assert summaries == {"accounts_manager": "Rent invoices, GST, arrears, and receivables."}


def test_skill_reader_raises_clear_error_for_missing_skill(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    with pytest.raises(SkillNotFoundError, match="Selected skill 'missing' was not found"):
        SkillReader(SkillRegistry(settings=make_settings(tmp_path, skills_dir))).read_skill("missing")
