from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# The schema is itself memory: a living index the agent curates over time.
# Python enforces HOW it may morph (types, naming, caps, soft-delete only);
# the LLM decides WHAT it should contain. Markdown remains the canonical
# source of truth — facts are derived projections, regenerable at any time.

ALLOWED_TYPES = {"string", "number", "boolean", "date", "list_of_strings"}
FIELD_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,49}$")
MAX_ACTIVE_FIELDS = 60

SEED_SCHEMA: dict[str, dict[str, str]] = {
    # Minimal seed; the agent expands/contracts it from here.
    "weekly_rent": {"type": "number", "description": "Current weekly rent in AUD."},
    "tenant_name": {"type": "string", "description": "Primary tenant or lessee name."},
    "lease_end_date": {"type": "date", "description": "Lease expiry date (YYYY-MM-DD)."},
    "owner_entity": {"type": "string", "description": "Owning entity for THIS asset (owners differ per asset)."},
}


class SchemaError(ValueError):
    pass


@dataclass
class SchemaStore:
    path: Path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            schema = self._seed()
            self._write(schema)
            return schema
        schema = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(schema, dict) or "fields" not in schema:
            raise SchemaError(f"Corrupt schema file at {self.path}.")
        return schema

    def active_fields(self) -> dict[str, dict[str, Any]]:
        return {
            name: spec
            for name, spec in self.load()["fields"].items()
            if spec.get("status") == "active"
        }

    # ------------------------------------------------------------------
    # Evolution — the only mutation API. Operations:
    #   add_field        — new active field (or revive a deprecated one)
    #   deprecate_field  — soft-remove; data is retained and revivable
    #   update_description — refine meaning without touching data
    # Type changes are deliberately not supported in place: deprecate the
    # old field and add a new one, so historical facts stay interpretable.
    # ------------------------------------------------------------------

    def evolve(self, operations: list[dict[str, Any]], reason: str) -> dict[str, Any]:
        if not operations:
            raise SchemaError("evolve requires at least one operation.")
        schema = self.load()
        fields: dict[str, Any] = schema["fields"]
        new_version = int(schema["version"]) + 1
        applied: list[str] = []

        for op in operations:
            if not isinstance(op, dict):
                raise SchemaError("Each operation must be an object.")
            action = op.get("op")
            name = str(op.get("field", "")).strip()
            if not FIELD_NAME_PATTERN.match(name):
                raise SchemaError(
                    f"Field name '{name}' must be snake_case, start with a letter, and be 2-50 chars."
                )

            if action == "add_field":
                field_type = op.get("type")
                description = str(op.get("description", "")).strip()
                if field_type not in ALLOWED_TYPES:
                    raise SchemaError(f"Type '{field_type}' not allowed. Allowed: {sorted(ALLOWED_TYPES)}.")
                if not description:
                    raise SchemaError(f"add_field '{name}' requires a description.")
                existing = fields.get(name)
                if existing and existing.get("status") == "active":
                    raise SchemaError(f"Field '{name}' already exists and is active.")
                if existing and existing.get("status") == "deprecated":
                    if existing.get("type") != field_type:
                        raise SchemaError(
                            f"Field '{name}' was deprecated with type '{existing.get('type')}'; "
                            "revive with the same type or choose a new name."
                        )
                    existing["status"] = "active"
                    existing["description"] = description
                    existing["revived_in"] = new_version
                    applied.append(f"revived {name}")
                else:
                    fields[name] = {
                        "type": field_type,
                        "description": description,
                        "status": "active",
                        "added_in": new_version,
                    }
                    applied.append(f"added {name} ({field_type})")

            elif action == "deprecate_field":
                spec = fields.get(name)
                if spec is None or spec.get("status") != "active":
                    raise SchemaError(f"Cannot deprecate '{name}': not an active field.")
                spec["status"] = "deprecated"
                spec["deprecated_in"] = new_version
                applied.append(f"deprecated {name}")

            elif action == "update_description":
                spec = fields.get(name)
                description = str(op.get("description", "")).strip()
                if spec is None:
                    raise SchemaError(f"Cannot update '{name}': unknown field.")
                if not description:
                    raise SchemaError(f"update_description '{name}' requires a description.")
                spec["description"] = description
                applied.append(f"updated description of {name}")

            else:
                raise SchemaError(
                    f"Unknown op '{action}'. Allowed: add_field, deprecate_field, update_description."
                )

        active_count = sum(1 for spec in fields.values() if spec.get("status") == "active")
        if active_count > MAX_ACTIVE_FIELDS:
            raise SchemaError(
                f"Schema would have {active_count} active fields (max {MAX_ACTIVE_FIELDS}). "
                "Deprecate unused fields before adding more."
            )

        schema["version"] = new_version
        schema["updated_at"] = datetime.now().isoformat(timespec="seconds")
        schema.setdefault("changelog", []).append(
            {"version": new_version, "changes": applied, "reason": reason.strip() or "unspecified"}
        )
        self._write(schema)
        return schema

    # ------------------------------------------------------------------

    def render(self) -> str:
        schema = self.load()
        lines = [f"Fact schema v{schema['version']} (active fields):"]
        for name, spec in sorted(schema["fields"].items()):
            if spec.get("status") != "active":
                continue
            lines.append(f"- {name} ({spec['type']}): {spec['description']}")
        deprecated = sorted(
            name for name, spec in schema["fields"].items() if spec.get("status") == "deprecated"
        )
        if deprecated:
            lines.append(f"Deprecated (revivable): {', '.join(deprecated)}")
        return "\n".join(lines)

    def _seed(self) -> dict[str, Any]:
        return {
            "version": 1,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "fields": {
                name: {**spec, "status": "active", "added_in": 1}
                for name, spec in SEED_SCHEMA.items()
            },
            "changelog": [{"version": 1, "changes": ["seed schema"], "reason": "initial"}],
        }

    def _write(self, schema: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
