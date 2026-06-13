from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.memory.assets import AssetRegistry
from src.memory.facts.registry import SchemaRegistry
from src.memory.paths import resolve_within
from src.memory.search.indexer import content_hash
from src.core.errors import UnsafeMemoryPathError

FACTS_FILE_NAME = "facts.json"
LEDGER_FILE_NAME = "facts_ledger.jsonl"


@dataclass
class FactReader:
    """Per-asset derived facts: a current-view projection over an
    append-only ledger.

    - ``facts.json``: latest value per field, with source file + hash.
    - ``facts_ledger.jsonl``: every value *change* as an event, so fact
      history (rent reviews, ownership changes) is never lost.
    - Staleness: each fact stores a hash of its source file at extraction
      time; if the file has changed since, the fact is flagged stale.

    Facts remain regenerable from markdown, so the schema can morph
    freely without data lock-in.
    """

    asset_registry: AssetRegistry
    schema_registry: SchemaRegistry

    def facts_path(self, asset_id: str) -> Path:
        return self.asset_registry.resolve_asset_dir(asset_id) / FACTS_FILE_NAME

    def ledger_path(self, asset_id: str) -> Path:
        return self.asset_registry.resolve_asset_dir(asset_id) / LEDGER_FILE_NAME

    def load(self, asset_id: str) -> dict[str, Any]:
        path = self.facts_path(asset_id)
        if not path.exists():
            return {"schema_version": None, "facts": {}}
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {"schema_version": None, "facts": {}}
        return payload

    def stale_fields(self, asset_id: str) -> dict[str, str]:
        """Fields whose source file changed since extraction (or vanished)."""
        stale: dict[str, str] = {}
        for name, entry in self.load(asset_id)["facts"].items():
            stored = entry.get("source_hash")
            if not stored:
                continue
            current = self.source_hash(asset_id, str(entry.get("source", "")))
            if current is None:
                stale[name] = "source file missing"
            elif current != stored:
                stale[name] = "source file changed since extraction"
        return stale

    def history(self, asset_id: str, field: str) -> list[dict[str, Any]]:
        path = self.ledger_path(asset_id)
        if not path.exists():
            return []
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("field") == field:
                events.append(event)
        return events

    def render(self, asset_id: str) -> str:
        payload = self.load(asset_id)
        facts = payload.get("facts", {})
        if not facts:
            return f"No facts recorded for '{asset_id}' yet. Use extract_facts after reading memory."
        active = set(self.schema_registry.active_fields())
        stale = self.stale_fields(asset_id)
        lines = [f"Facts for {asset_id} (schema v{payload.get('schema_version')}):"]
        for name, entry in sorted(facts.items()):
            flags = []
            if name not in active:
                flags.append("field deprecated")
            if name in stale:
                flags.append(f"STALE: {stale[name]} — run extract_facts")
            flag_text = f" [{'; '.join(flags)}]" if flags else ""
            lines.append(f"- {name} = {entry.get('value')!r} (source: {entry.get('source')}){flag_text}")
        return "\n".join(lines)

    def source_hash(self, asset_id: str, source: str) -> str | None:
        if not source or source == "unknown":
            return None
        try:
            path = resolve_within(self.asset_registry.resolve_asset_dir(asset_id), source, label="Fact source path")
        except UnsafeMemoryPathError:
            return None
        if not path.exists() or not path.is_file():
            return None
        return content_hash(path.read_text(encoding="utf-8", errors="replace"))
