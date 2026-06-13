from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.memory.assets import AssetRegistry
from src.memory.facts.reader import FactReader
from src.memory.facts.registry import SchemaRegistry

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class FactWriter:
    asset_registry: AssetRegistry
    schema_registry: SchemaRegistry
    reader: FactReader

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
        active = self.schema_registry.active_fields()
        existing = self.reader.load(asset_id)["facts"]
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
                "source_hash": self.reader.source_hash(asset_id, source),
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
            "schema_version": self.schema_registry.load()["version"],
            "updated_at": now,
            "facts": merged,
        }
        path = self.reader.facts_path(asset_id)
        if not path.parent.exists():
            raise FileNotFoundError(f"Asset directory does not exist for '{asset_id}'.")
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if events:
            with self.reader.ledger_path(asset_id).open("a", encoding="utf-8") as ledger:
                for event in events:
                    ledger.write(json.dumps(event) + "\n")
        return payload, rejected


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
