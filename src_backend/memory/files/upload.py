from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from src_backend.core.constants import ALLOWED_MEMORY_EXTENSIONS
from src_backend.core.errors import LLMProviderError, UnsafeMemoryPathError
from src_backend.llm.client import LLMClient
from src_backend.memory.assets import AssetRegistry
from src_backend.memory.files.extractors import extract_to_markdown
from src_backend.memory.files.writer import FileWriter


class FileUploader:
    """File-ingestion pipeline: save uploads, organise them under an asset's
    ``Files/`` folder, and extract searchable text + summary sidecars.

    Kept separate from the web layer so the front end stays thin: it only
    receives bytes/requests and calls into this service.
    """

    def __init__(
        self,
        file_writer: FileWriter,
        asset_registry: AssetRegistry,
        llm_client: LLMClient,
        uploads_dir: Path,
    ) -> None:
        self.file_writer = file_writer
        self.asset_registry = asset_registry
        self.llm_client = llm_client
        self.uploads_dir = uploads_dir

    def save_to_asset(self, asset_id: str, filename: str, content: bytes) -> str:
        """Save an upload directly into an asset's Files/ folder, renaming on
        collision. Triggers background text extraction for non-memory files."""
        final_name = filename
        try:
            self.file_writer.write_bytes(asset_id, f"Files/{final_name}", content)
        except UnsafeMemoryPathError:
            final_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{final_name}"
            self.file_writer.write_bytes(asset_id, f"Files/{final_name}", content)
        self._trigger_extraction(asset_id, final_name)
        return final_name

    def save_generic(self, filename: str, content: bytes) -> str:
        """Save an upload with no asset context yet, renaming on collision."""
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        path = self.uploads_dir / filename
        final_name = filename
        if path.exists():
            final_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
            path = self.uploads_dir / final_name
        path.write_bytes(content)
        return final_name

    def assign(self, filename: str, asset_id: str) -> str | None:
        """Move a previously-saved generic upload into an asset's Files/
        folder. Returns the final filename, or None if no such generic
        upload exists."""
        source = self.uploads_dir / Path(filename).name
        if not source.is_file():
            return None

        content = source.read_bytes()
        final_name = self.save_to_asset(asset_id, source.name, content)
        source.unlink()
        return final_name

    def _trigger_extraction(self, asset_id: str, filename: str) -> None:
        if Path(filename).suffix.lower() in ALLOWED_MEMORY_EXTENSIONS:
            return
        asset_dir = self.asset_registry.resolve_asset_dir(asset_id)
        if (asset_dir / "Files" / f"{filename}.md").exists():
            # Already extracted, e.g. as a byproduct of a codex_agent task
            # that analysed this file during the same run.
            return
        if self._extract_deterministically(asset_id, filename):
            return
        threading.Thread(
            target=self._extract, args=(asset_id, filename), daemon=True
        ).start()

    def _extract_deterministically(self, asset_id: str, filename: str) -> bool:
        """Convert structured office files (spreadsheets, CSV, Word docs) to
        Markdown with a local library instead of an LLM call. Returns True if
        handled, False if the format needs the codex_agent fallback."""
        asset_dir = self.asset_registry.resolve_asset_dir(asset_id)
        try:
            result = extract_to_markdown(asset_dir / "Files" / filename)
        except Exception:
            return False
        if result is None:
            return False
        markdown, summary = result
        self.file_writer.write_bytes(asset_id, f"Files/{filename}.md", markdown.encode("utf-8"))
        self.file_writer.write_json(asset_id, f"Files/{filename}.md.meta.json", {"summary": summary})
        return True

    def _extract(self, asset_id: str, filename: str) -> None:
        """Best-effort: ask the Codex sub-agent to turn an uploaded binary/office
        file into a searchable Markdown extract plus a summary sidecar, so
        search_memory and read_memory can see its content like any other
        memory file."""
        asset_dir = self.asset_registry.resolve_asset_dir(asset_id)
        task = (
            f"A file named 'Files/{filename}' was just uploaded to this asset's memory folder. "
            "Read its content and create two new files (do not modify or delete any other files):\n"
            f"1. 'Files/{filename}.md' - a Markdown extract of its key textual content "
            "(preserve tables as Markdown tables, keep important figures, dates, and clauses).\n"
            f"2. 'Files/{filename}.md.meta.json' - a JSON object with a single field "
            '"summary": a 1-2 sentence plain-text summary of the document.'
        )
        try:
            self.llm_client.run_agentic(
                task,
                sandbox="workspace-write",
                enable_search=False,
                working_dir=str(asset_dir),
                timeout_seconds=180,
            )
        except LLMProviderError:
            pass
