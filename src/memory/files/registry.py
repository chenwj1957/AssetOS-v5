from __future__ import annotations

import json
from pathlib import Path

from src.memory.assets import AssetRegistry
from src.core.config import Settings
from src.core.constants import ALLOWED_MEMORY_EXTENSIONS
from src.core.errors import UnsafeMemoryPathError
from src.core.types import File


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
                    summary=self._load_file_summary(path),
                )
            )
        return files

    def list_files_by_assets(self, asset_ids: list[str]) -> dict[str, list[File]]:
        return {
            asset_id: self.list_files_by_asset(asset_id)
            for asset_id in asset_ids
        }

    def _load_file_summary(self, path: Path) -> str:
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
        candidate = Path(selected_file)
        if candidate.is_absolute():
            raise UnsafeMemoryPathError(f"Memory file path must be relative to the asset directory: {selected_file}")
        if ".." in candidate.parts:
            raise UnsafeMemoryPathError(f"Memory file path cannot contain parent-directory references: {selected_file}")

        asset_dir = self.asset_registry.resolve_asset_dir(asset_id).resolve()
        resolved = (asset_dir / candidate).resolve()
        try:
            resolved.relative_to(asset_dir)
        except ValueError as exc:
            raise UnsafeMemoryPathError(f"Memory file path escapes the asset directory: {selected_file}") from exc
        return resolved
