from __future__ import annotations

import re
import shutil
from pathlib import Path

from src.core.errors import UnsafeMemoryPathError
from src.memory.assets.registry import AssetRegistry
from src.memory.paths import resolve_within


class AssetWriter:
    def __init__(self, registry: AssetRegistry) -> None:
        self.registry = registry

    def create_asset(
        self,
        asset_id: str | None = None,
        *,
        display_name: str | None = None,
        profile_content: str | None = None,
    ) -> Path:
        resolved_asset_id = self._resolve_asset_id(asset_id, display_name)
        dir_asset = self._resolve_new_asset_dir(resolved_asset_id)
        profile_path = dir_asset / "profile.md"
        template_dir = self._template_dir()

        if template_dir.exists() and template_dir.is_dir():
            # Start new asset folders from the shared placeholder structure, then apply the generated profile.
            shutil.copytree(template_dir, dir_asset)
        else:
            dir_files = dir_asset / "Files"
            dir_artifact = dir_asset / "Artifact"
            dir_files.mkdir(parents=True, exist_ok=False)
            dir_artifact.mkdir(parents=True, exist_ok=False)
        profile_path.write_text(
            profile_content if profile_content is not None else self._default_profile(display_name or resolved_asset_id),
            encoding="utf-8",
        )

        return dir_asset

    def _resolve_asset_id(self, asset_id: str | None, display_name: str | None) -> str:
        source = asset_id or display_name
        if source is None or not source.strip():
            raise ValueError("Asset creation requires an asset_id or display_name.")
        return self.slugify_asset_id(source)

    def _resolve_new_asset_dir(self, asset_id: str) -> Path:
        dir_asset = resolve_within(self.registry.assets_dir, asset_id, label=f"Asset path '{asset_id}'")
        if dir_asset.exists():
            raise UnsafeMemoryPathError(f"Asset memory folder already exists: {asset_id}")
        return dir_asset

    def _template_dir(self) -> Path:
        return self.registry.settings.dir_data / "memory_template" / "asset" / "default"

    @staticmethod
    def slugify_asset_id(value: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9]+", "_", value.strip())
        slug = re.sub(r"_+", "_", slug).strip("_")
        if not slug:
            raise ValueError("Asset id must contain at least one letter or number.")
        return slug

    @staticmethod
    def _default_profile(display_name: str) -> str:
        return (
            f"# {display_name}\n\n"
            "## Summary\n\n"
            "New asset profile. Add property details, ownership context, tenant information, "
            "key dates, and operating notes here.\n"
        )
