from pathlib import Path

import pytest

from src.core.config import Settings
from src.core.errors import MemoryNotFoundError, UnsafeMemoryPathError
from src.memory.assets import AssetRegistry
from src.memory.files.registry import FileRegistry
from src.memory.files.reader import FileReader


def make_settings(tmp_path: Path, assets_dir: Path | None = None, memory_file_max_bytes: int | None = None) -> Settings:
    kwargs = {}
    if memory_file_max_bytes is not None:
        kwargs["memory_file_max_bytes"] = memory_file_max_bytes
    return Settings(
        project_root=tmp_path,
        dir_data=tmp_path,
        dir_skills=tmp_path / "skills",
        dir_assets=assets_dir or tmp_path / "assets",
        ollama_url="",
        ollama_model="",
        codex_model="",
        **kwargs,
    )


def make_file_registry(tmp_path: Path, assets_dir: Path | None = None, memory_file_max_bytes: int | None = None) -> FileRegistry:
    settings = make_settings(tmp_path, assets_dir=assets_dir, memory_file_max_bytes=memory_file_max_bytes)
    return FileRegistry(
        settings=settings,
        asset_registry=AssetRegistry(settings=settings),
    )


def test_file_reader_loads_asset_file(tmp_path: Path) -> None:
    asset_dir = tmp_path / "assets" / "asset #1"
    asset_dir.mkdir(parents=True)
    (asset_dir / "profile.md").write_text("Asset facts", encoding="utf-8")

    file = FileReader(make_file_registry(tmp_path)).read_file("asset #1", "profile.md")

    assert file.asset_id == "asset #1"
    assert file.content == "Asset facts"
    assert file.summary == "memory file"


def test_file_registry_lists_files_by_assets(tmp_path: Path) -> None:
    first_asset_dir = tmp_path / "assets" / "asset #1"
    second_asset_dir = tmp_path / "assets" / "asset #2" / "reports"
    first_asset_dir.mkdir(parents=True)
    second_asset_dir.mkdir(parents=True)
    (first_asset_dir / "profile.md").write_text("Asset facts", encoding="utf-8")
    (second_asset_dir / "fire.txt").write_text("Fire report", encoding="utf-8")
    (second_asset_dir / "ignore.pdf").write_text("Unsupported", encoding="utf-8")

    files_by_asset = make_file_registry(tmp_path).list_files_by_assets(
        ["asset #1", "asset #2"]
    )

    assert {
        asset_id: [file.file_name for file in files]
        for asset_id, files in files_by_asset.items()
    } == {
        "asset #1": ["profile.md"],
        "asset #2": [str(Path("reports") / "fire.txt")],
    }
    assert files_by_asset["asset #1"][0].path == first_asset_dir / "profile.md"


def test_file_registry_lists_files_with_summaries_by_asset(tmp_path: Path) -> None:
    asset_dir = tmp_path / "assets" / "asset #1"
    asset_dir.mkdir(parents=True)
    (asset_dir / "profile.md").write_text("Asset facts", encoding="utf-8")
    (asset_dir / "Lease agreement.md").write_text("Lease facts", encoding="utf-8")

    files = make_file_registry(tmp_path).list_files_by_asset("asset #1")

    assert [
        {"file": file.file_name, "summary": file.summary}
        for file in files
    ] == [
        {"file": "Lease agreement.md", "summary": "memory file"},
        {"file": "profile.md", "summary": "memory file"},
    ]


def test_file_registry_lists_single_file_entry_by_asset(tmp_path: Path) -> None:
    asset_dir = tmp_path / "assets" / "asset #1"
    asset_dir.mkdir(parents=True)
    (asset_dir / "profile.md").write_text("Asset facts", encoding="utf-8")

    files = make_file_registry(tmp_path).list_files_by_asset("asset #1")

    assert len(files) == 1
    assert files[0].file_name == "profile.md"
    assert files[0].summary == "memory file"
    assert files[0].path == asset_dir / "profile.md"


def test_file_registry_prefers_file_metadata_summary(tmp_path: Path) -> None:
    asset_dir = tmp_path / "assets" / "asset #1"
    asset_dir.mkdir(parents=True)
    (asset_dir / "Lease agreement.md").write_text("Lease facts", encoding="utf-8")
    (asset_dir / "Lease agreement.md.meta.json").write_text(
        '{"summary": "Current lease terms for rent invoicing."}',
        encoding="utf-8",
    )

    files_by_asset = make_file_registry(tmp_path).list_files_by_assets(["asset #1"])

    assert [
        {"file": file.file_name, "summary": file.summary}
        for file in files_by_asset["asset #1"]
    ] == [
        {"file": "Lease agreement.md", "summary": "Current lease terms for rent invoicing."}
    ]


def test_file_reader_loads_file_summary_from_metadata(tmp_path: Path) -> None:
    asset_dir = tmp_path / "assets" / "asset #1"
    asset_dir.mkdir(parents=True)
    (asset_dir / "profile.md").write_text("Asset facts", encoding="utf-8")
    (asset_dir / "profile.md.meta.json").write_text(
        '{"summary": "Asset profile.", "source": "manual"}',
        encoding="utf-8",
    )

    file = FileReader(make_file_registry(tmp_path)).read_file("asset #1", "profile.md")

    assert file.summary == "Asset profile."


def test_file_reader_raises_for_missing_file(tmp_path: Path) -> None:
    asset_dir = tmp_path / "assets" / "asset #1"
    asset_dir.mkdir(parents=True)

    with pytest.raises(MemoryNotFoundError, match="Selected memory file 'missing.md'"):
        FileReader(make_file_registry(tmp_path)).read_file("asset #1", "missing.md")


def test_file_reader_rejects_absolute_paths(tmp_path: Path) -> None:
    asset_dir = tmp_path / "assets" / "asset #1"
    asset_dir.mkdir(parents=True)

    with pytest.raises(UnsafeMemoryPathError):
        FileReader(make_file_registry(tmp_path)).read_file("asset #1", str((tmp_path / "secret.md").resolve()))


def test_file_reader_rejects_parent_directory_traversal(tmp_path: Path) -> None:
    asset_dir = tmp_path / "assets" / "asset #1"
    asset_dir.mkdir(parents=True)

    with pytest.raises(UnsafeMemoryPathError):
        FileReader(make_file_registry(tmp_path)).read_file("asset #1", "../secret.md")


def test_file_reader_rejects_asset_id_traversal(tmp_path: Path) -> None:
    (tmp_path / "assets" / "asset #1").mkdir(parents=True)
    (tmp_path / "secret.md").write_text("top secret", encoding="utf-8")

    registry = make_file_registry(tmp_path)
    for malicious_asset_id in ("..", "../secret", "../", "/etc", "a/b"):
        with pytest.raises(UnsafeMemoryPathError):
            FileReader(registry).read_file(malicious_asset_id, "secret.md")


def test_file_reader_enforces_file_size_limit(tmp_path: Path) -> None:
    asset_dir = tmp_path / "assets" / "asset #1"
    asset_dir.mkdir(parents=True)
    (asset_dir / "profile.md").write_text("too long", encoding="utf-8")
    settings = Settings(
        project_root=tmp_path,
        dir_data=tmp_path / "data",
        dir_skills=tmp_path / "data" / "skills",
        dir_assets=tmp_path / "assets",
        ollama_url="",
        ollama_model="",
        codex_model="",
        memory_file_max_bytes=3,
    )

    with pytest.raises(MemoryNotFoundError, match="exceeds"):
        FileReader(FileRegistry(settings=settings, asset_registry=AssetRegistry(settings=settings))).read_file("asset #1", "profile.md")
