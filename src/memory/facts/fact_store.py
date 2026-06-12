from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.memory.assets import AssetRegistry
from src.memory.facts.schema_store import SchemaStore
from src.memory.search.indexer import content_hash

FACTS_FILE_NAME = "facts.json"
LEDGER_FILE_NAME = "facts_ledger.jsonl"
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class FactStore:
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
    schema_store: SchemaStore

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

    # ------------------------------------------------------------------

    def save(
        self,
        asset_id: str,
        extracted: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        """Validate against the active schema, persist, and ledger changes.

        Returns (saved_payload, rejected_field_notes). Unknown fields are
        rejected but reported so the agent can evolve the schema and
        re-extract — the feedback loop that grows the schema.
        """
        active = self.schema_store.active_fields()
        existing = self.load(asset_id)["facts"]
        rejected: list[str] = []
        merged: dict[str, Any] = dict(existing)
        events: list[dict[str, Any]] = []
        now = datetime.now().isoformat(timespec="seconds")

        for name, entry in extracted.items():
            if name not in active:
                rejected.append(f"'{name}' is not in the active schema (use evolve_schema to add it)")
                continue
            if not isinstance(entry, dict) or "value" not in entry:
                rejected.append(f"'{name}' must be an object with at least a 'value' key")
                continue
            value = entry["value"]
            error = _type_error(value, active[name]["type"])
            if error:
                rejected.append(f"'{name}': {error}")
                continue
            source = str(entry.get("source", "unknown"))
            previous = existing.get(name, {}).get("value")
            merged[name] = {
                "value": value,
                "source": source,
                "source_hash": self._source_hash(asset_id, source),
                "extracted_at": now,
            }
            if value != previous:
                events.append(
                    {
                        "field": name,
                        "value": value,
                        "previous_value": previous,
                        "source": source,
                        "recorded_at": now,
                    }
                )

        payload = {
            "schema_version": self.schema_store.load()["version"],
            "updated_at": now,
            "facts": merged,
        }
        path = self.facts_path(asset_id)
        if not path.parent.exists():
            raise FileNotFoundError(f"Asset directory does not exist for '{asset_id}'.")
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if events:
            with self.ledger_path(asset_id).open("a", encoding="utf-8") as ledger:
                for event in events:
                    ledger.write(json.dumps(event) + "\n")
        return payload, rejected

    # ------------------------------------------------------------------

    def stale_fields(self, asset_id: str) -> dict[str, str]:
        """Fields whose source file changed since extraction (or vanished)."""
        stale: dict[str, str] = {}
        for name, entry in self.load(asset_id)["facts"].items():
            stored = entry.get("source_hash")
            if not stored:
                continue
            current = self._source_hash(asset_id, str(entry.get("source", "")))
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
        active = set(self.schema_store.active_fields())
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

    def _source_hash(self, asset_id: str, source: str) -> str | None:
        if not source or source == "unknown":
            return None
        candidate = Path(source)
        if candidate.is_absolute() or ".." in candidate.parts:
            return None
        path = self.asset_registry.resolve_asset_dir(asset_id) / candidate
        if not path.exists() or not path.is_file():
            return None
        return content_hash(path.read_text(encoding="utf-8", errors="replace"))


def _type_error(value: Any, expected: str) -> str | None:
    if value is None:
        return None  # explicit unknown is allowed
    if expected == "string":
        return None if isinstance(value, str) else f"expected string, got {type(value).__name__}"
    if expected == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"expected number, got {type(value).__name__}"
        return None
    if expected == "boolean":
        return None if isinstance(value, bool) else f"expected boolean, got {type(value).__name__}"
    if expected == "date":
        if isinstance(value, str) and DATE_PATTERN.match(value):
            return None
        return "expected date string in YYYY-MM-DD format"
    if expected == "list_of_strings":
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return None
        return "expected a list of strings"
    return f"unknown schema type '{expected}'"
