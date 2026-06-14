from __future__ import annotations

import json
from pathlib import Path

from src_backend.memory.assets import AssetRegistry
from src_backend.core.config import Settings
from src_backend.core.constants import ALLOWED_MEMORY_EXTENSIONS
from src_backend.core.types import File
from src_backend.memory.paths import resolve_within


class FileRegistry:
    def __init__(self, settings: Settings, asset_registry: AssetRegistry) -> None:
        self.settings = settings
        self.asset_registry = asset_registry

    def list_files_by_asset(self, asset_id: str) -> list[File]:
        asset_dir = self.asset_registry.resolve_asset_dir(asset_id)
        if not asset_dir.exists():
            return []
        paths = sorted(
            path
            for path in asset_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in ALLOWED_MEMORY_EXTENSIONS
        )
        files: list[File] = []
        for path in paths:
            file_name = str(path.relative_to(asset_dir))
            files.append(
                File(
                    asset_id=asset_id,
                    file_name=file_name,
                    path=path,
                    summary=self.load_file_summary(path),
                )
            )
        return files

    def list_artifacts_by_asset(self, asset_id: str) -> list[str]:
        artifact_dir = self.asset_registry.resolve_asset_dir(asset_id) / "Artifact"
        if not artifact_dir.exists():
            return []
        return sorted(p.name for p in artifact_dir.iterdir() if p.is_file() and p.suffix == ".docx")

    def list_all_files_by_asset(self, asset_id: str) -> list[File]:
        """All files under the asset's Files/ folder, for the vault UI's
        "Memory files" listing. Unlike :meth:`list_files_by_asset`, this
        includes every file type (e.g. source PDFs alongside their .md
        extracts) but excludes .meta.json sidecars."""
        files_dir = self.asset_registry.resolve_asset_dir(asset_id) / "Files"
        if not files_dir.exists():
            return []
        paths = sorted(
            p for p in files_dir.iterdir() if p.is_file() and not p.name.endswith(".meta.json")
        )
        return [
            File(asset_id=asset_id, file_name=p.name, path=p, summary=self.load_file_summary(p))
            for p in paths
        ]

    def list_run_names(self, asset_id: str) -> list[str]:
        runs_dir = self.asset_registry.resolve_asset_dir(asset_id) / "runs"
        if not runs_dir.exists():
            return []
        return sorted((p.name for p in runs_dir.iterdir() if p.is_file() and p.suffix == ".md"), reverse=True)

    def list_files_by_assets(self, asset_ids: list[str]) -> dict[str, list[File]]:
        return {
            asset_id: self.list_files_by_asset(asset_id)
            for asset_id in asset_ids
        }

    def load_file_summary(self, path: Path) -> str:
        metadata_path = path.with_name(f"{path.name}.meta.json")
        if not metadata_path.exists() or not metadata_path.is_file():
            return "memory file"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            return "memory file"
        summary = metadata.get("summary")
        if isinstance(summary, str) and summary.strip():
            return " ".join(summary.split())
        return "memory file"

    def resolve_safe_file_path(self, asset_id: str, selected_file: str) -> Path:
        asset_dir = self.asset_registry.resolve_asset_dir(asset_id)
        return resolve_within(asset_dir, selected_file, label=f"Memory file path '{selected_file}'")
