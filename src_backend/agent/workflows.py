from __future__ import annotations

import json
from pathlib import Path

DEFAULT_WORKFLOWS: list[dict[str, str]] = [
    {
        "name": "Arrears sweep",
        "task": "Review every asset for rent arrears or overdue amounts. For anything 7+ days late, draft a reminder note and save it to that asset's memory. Summarise portfolio arrears.",
    },
    {
        "name": "Lease expiry watch",
        "task": "Check lease_end_date across all assets. Flag any lease expiring within 90 days and recommend next steps (renewal terms, market rent check).",
    },
    {
        "name": "Draft rent invoice",
        "task": "Draft this month's rent invoice for {asset}: read its memory, generate the invoice data, and build the DOCX.",
    },
    {
        "name": "Facts freshness check",
        "task": "For each asset, query facts and re-extract any flagged STALE so the fact layer is current.",
    },
]


class WorkflowStore:
    """Persists saved task presets ("workflows") shown in the composer UI."""

    def __init__(self, path: Path, defaults: list[dict[str, str]] | None = None) -> None:
        self.path = path
        self.defaults = defaults if defaults is not None else DEFAULT_WORKFLOWS

    def load(self) -> list[dict[str, str]]:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"workflows": self.defaults}, indent=2), encoding="utf-8")
        return json.loads(self.path.read_text(encoding="utf-8")).get("workflows", [])

    def add(self, name: str, task: str) -> list[dict[str, str]]:
        workflows = self.load()
        workflows.append({"name": name, "task": task})
        self.path.write_text(json.dumps({"workflows": workflows}, indent=2), encoding="utf-8")
        return workflows
