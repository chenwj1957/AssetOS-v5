from __future__ import annotations

from src.core.errors import MemoryNotFoundError
from src.core.types import File
from src.memory.files.registry import FileRegistry


class FileReader:
    def __init__(self, registry: FileRegistry) -> None:
        self.registry = registry

    def read_file(self, asset_id: str, selected_file: str) -> File:
        path = self.registry.resolve_safe_file_path(asset_id, selected_file)
        if not path.exists() or not path.is_file():
            available = ", ".join(
                file.file_name
                for file in self.registry.list_files_by_asset(asset_id)
            )
            available = available or "none"
            raise MemoryNotFoundError(
                f"Selected memory file '{selected_file}' for asset '{asset_id}' was not found at {path}. "
                f"Available memory files: {available}."
            )
        if path.stat().st_size > self.registry.settings.memory_file_max_bytes:
            raise MemoryNotFoundError(
                f"Selected memory file '{selected_file}' for asset '{asset_id}' exceeds "
                f"{self.registry.settings.memory_file_max_bytes} bytes."
            )
        return File(
            asset_id=asset_id,
            file_name=selected_file,
            path=path,
            summary=self.registry._load_file_summary(path),
            content=path.read_text(encoding="utf-8"),
        )

    def read_files(self, asset_id: str | None, selected_files: list[str]) -> list[File]:
        if not selected_files:
            return []
        if not asset_id:
            raise MemoryNotFoundError("Memory files were selected, but no asset_id was provided by routing.")
        if len(selected_files) > self.registry.settings.memory_file_max_number:
            raise MemoryNotFoundError(
                f"Too many memory files selected: {len(selected_files)}. "
                f"Maximum allowed is {self.registry.settings.memory_file_max_number}."
            )
        return [self.read_file(asset_id, selected_file) for selected_file in selected_files]
