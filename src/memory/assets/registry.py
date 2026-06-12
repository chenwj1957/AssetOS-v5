from __future__ import annotations

from pathlib import Path

from src.core.config import Settings


class AssetRegistry:
    def __init__(self, settings: Settings, assets_dir: Path | None = None) -> None:
        self.settings = settings
        self.assets_dir = assets_dir or self.settings.dir_assets

    def list_asset_ids(self) -> list[str]:
        if not self.assets_dir.exists():
            return []
        return sorted(path.name for path in self.assets_dir.iterdir() if path.is_dir())

    def resolve_asset_dir(self, asset_id: str) -> Path:
        return self.assets_dir / asset_id

    def list_asset_profiles(self) -> dict[str, str]:
        profiles: dict[str, str] = {}
        for asset_id in self.list_asset_ids():
            profile_path = self.resolve_asset_dir(asset_id) / "profile.md"
            if profile_path.exists() and profile_path.is_file():
                profiles[asset_id] = profile_path.read_text(encoding="utf-8")
        return profiles
