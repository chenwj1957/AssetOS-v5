from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.core.errors import UnsafeMemoryPathError
from src.memory.files.registry import FileRegistry


class FileWriter:
    def __init__(self, registry: FileRegistry) -> None:
        self.registry = registry

    def write_bytes(self, asset_id: str, relative_path: str, content: bytes) -> Path:
        path = self._resolve_new_file_path(asset_id, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def write_json(self, asset_id: str, relative_path: str, content: dict[str, Any]) -> Path:
        path = self._resolve_new_file_path(asset_id, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content, indent=2), encoding="utf-8")
        return path

    def _resolve_new_file_path(self, asset_id: str, relative_path: str) -> Path:
        path = self.registry.resolve_safe_file_path(asset_id, relative_path)
        if path.exists():
            raise UnsafeMemoryPathError(f"Asset memory output already exists: {relative_path}")
        return path
