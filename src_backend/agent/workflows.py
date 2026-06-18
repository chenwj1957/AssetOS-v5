from __future__ import annotations

import json
from pathlib import Path
from typing import Any

Workflow = dict[str, Any]

DEFAULT_WORKFLOWS: list[Workflow] = [
    {
        "name": "Arrears sweep",
        "type": "arrears_sweep",
        "task": "Review every asset for rent arrears or overdue amounts. For anything 7+ days late, draft a reminder note and save it to that asset's memory. Summarise portfolio arrears.",
        "required_inputs": [],
        "expected_outputs": ["portfolio arrears summary", "asset-level reminder drafts", "saved memory notes"],
        "steps": [
            "List all assets and query rent/payment facts.",
            "Calculate arrears and classify anything 7+ days late.",
            "Draft reminder wording for each affected tenancy.",
            "Save durable notes against affected assets and summarise portfolio exposure.",
        ],
        "approval_required_for": ["send_email", "create_notice", "external_system_update"],
    },
    {
        "name": "Lease expiry watch",
        "type": "lease_expiry_watch",
        "task": "Check lease_end_date across all assets. Flag any lease expiring within 90 days and recommend next steps (renewal terms, market rent check).",
        "required_inputs": [],
        "expected_outputs": ["expiry list", "renewal/rent-review recommendations", "follow-up tasks"],
        "steps": [
            "Query lease_end_date for every asset and refresh stale facts.",
            "Identify leases expiring within 90 days.",
            "Recommend renewal, rent review, or vacate preparation actions.",
            "Create follow-up task recommendations with dates and evidence.",
        ],
        "approval_required_for": ["send_email", "create_notice", "external_system_update"],
    },
    {
        "name": "Draft rent invoice",
        "type": "rent_invoice",
        "task": "Draft this month's rent invoice for {asset}: read its memory, generate the invoice data, and build the DOCX.",
        "required_inputs": ["asset"],
        "expected_outputs": ["validated invoice data", "DOCX invoice artifact", "source/provenance sidecar"],
        "steps": [
            "Read the asset profile and payment/rent facts.",
            "Use calculate for GST, totals, and any pro-rata amounts.",
            "Generate validated invoice JSON.",
            "Render the DOCX artifact under the active asset.",
        ],
        "approval_required_for": ["send_email", "external_system_update"],
    },
    {
        "name": "Facts freshness check",
        "type": "facts_freshness_check",
        "task": "For each asset, query facts and re-extract any flagged STALE so the fact layer is current.",
        "required_inputs": [],
        "expected_outputs": ["stale fact list", "refreshed fact projections", "schema candidate notes"],
        "steps": [
            "List assets and query facts for each one.",
            "Re-extract facts where stale fields are reported.",
            "Report recurring unschema'd candidates for schema evolution.",
            "Summarise assets that still need manual source updates.",
        ],
        "approval_required_for": [],
    },
]


class WorkflowStore:
    """Persists saved task presets ("workflows") shown in the composer UI."""

    def __init__(self, path: Path, defaults: list[Workflow] | None = None) -> None:
        self.path = path
        self.defaults = defaults if defaults is not None else DEFAULT_WORKFLOWS

    def load(self) -> list[Workflow]:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"workflows": self.defaults}, indent=2), encoding="utf-8")
        workflows = json.loads(self.path.read_text(encoding="utf-8")).get("workflows", [])
        return [self._normalise(workflow) for workflow in workflows if isinstance(workflow, dict)]

    def add(self, name: str, task: str, workflow_type: str = "custom") -> list[Workflow]:
        workflows = self.load()
        workflows.append(
            self._normalise(
                {
                    "name": name,
                    "type": workflow_type,
                    "task": task,
                    "required_inputs": [],
                    "expected_outputs": ["agent answer or draft"],
                    "steps": ["Run the saved instruction and ground the answer in asset memory where relevant."],
                    "approval_required_for": [],
                }
            )
        )
        self.path.write_text(json.dumps({"workflows": workflows}, indent=2), encoding="utf-8")
        return workflows

    def _normalise(self, workflow: Workflow) -> Workflow:
        """Return a typed workflow template while preserving old saved presets.

        v5.5 stored workflows as only {name, task}.  Priority 5 promotes those
        presets into templates with metadata the UI and future orchestrators can
        inspect without breaking existing data/workflows.json files.
        """
        name = str(workflow.get("name") or "Untitled workflow")
        task = str(workflow.get("task") or "")
        workflow_type = str(workflow.get("type") or "custom")
        return {
            "name": name,
            "type": workflow_type,
            "task": task,
            "required_inputs": self._string_list(workflow.get("required_inputs")),
            "expected_outputs": self._string_list(workflow.get("expected_outputs")),
            "steps": self._string_list(workflow.get("steps")) or [task],
            "approval_required_for": self._string_list(workflow.get("approval_required_for")),
        }

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]
