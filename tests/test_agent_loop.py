from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.agent import AgentLoop
from src.core.config import Settings


def make_settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    (data / "memory" / "assets").mkdir(parents=True)
    (data / "memory" / "skills").mkdir(parents=True)
    return Settings(
        project_root=tmp_path,
        dir_data=data,
        dir_skills=data / "memory" / "skills",
        dir_assets=data / "memory" / "assets",
        ollama_url="http://localhost:11434",
        ollama_model="fake-ollama",
        codex_model="fake-codex",
        max_iterations=6,
    )


class ScriptedLLM:
    """Returns queued JSON decisions; records prompts it received."""

    def __init__(self, decisions: list[dict[str, Any]]) -> None:
        self.decisions = list(decisions)
        self.prompts: list[str] = []

    def generate_json(self, prompt: str, provider: str = "codex") -> dict[str, Any]:
        self.prompts.append(prompt)
        if not self.decisions:
            return {"thought": "done", "final_answer": "fallback"}
        return self.decisions.pop(0)

    def generate_text(self, prompt: str, provider: str = "codex") -> str:
        return "text"

    def run_agentic(self, task: str, **kwargs: Any) -> str:
        return f"AGENTIC:{task[:40]}"


def seed_asset(settings: Settings, asset_id: str = "12_ocean_st") -> None:
    asset_dir = settings.dir_assets / asset_id
    asset_dir.mkdir(parents=True)
    (asset_dir / "profile.md").write_text("# 12 Ocean St\nA two-unit residential asset.", encoding="utf-8")
    (asset_dir / "lease.md").write_text("Rent: $1000/week. Tenant: J. Smith.", encoding="utf-8")


def test_loop_reads_memory_then_finishes(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_asset(settings)
    llm = ScriptedLLM(
        [
            {"thought": "see what assets exist", "action": {"tool": "list_assets", "args": {}}},
            {
                "thought": "read the lease",
                "action": {"tool": "read_memory", "args": {"asset_id": "12_ocean_st", "files": ["profile.md", "lease.md"]}},
            },
            {"thought": "answer", "final_answer": "Weekly rent is $1000."},
        ]
    )
    state = AgentLoop(settings=settings, llm_client=llm, emit=lambda _: None).run("What is the rent at 12 Ocean St?")

    assert state.answer == "Weekly rent is $1000."
    assert state.selected_asset == "12_ocean_st"
    assert [t.tool for t in state.turns] == ["list_assets", "read_memory"]
    assert "Rent: $1000/week" in state.turns[1].observation
    # Memory content must be flagged as untrusted in the observation.
    assert "Untrusted asset memory" in state.turns[1].observation


def test_loop_recovers_from_unknown_tool_and_bad_args(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_asset(settings)
    llm = ScriptedLLM(
        [
            {"thought": "oops", "action": {"tool": "teleport", "args": {}}},
            {"thought": "bad args", "action": {"tool": "read_memory", "args": {"asset_id": "12_ocean_st"}}},
            {"thought": "fixed", "final_answer": "recovered"},
        ]
    )
    state = AgentLoop(settings=settings, llm_client=llm, emit=lambda _: None).run("test")
    assert "unknown tool" in state.turns[0].observation
    assert "ERROR" in state.turns[1].observation
    assert state.answer == "recovered"


def test_loop_hits_iteration_limit_gracefully(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    llm = ScriptedLLM(
        [{"thought": "loop", "action": {"tool": "list_skills", "args": {}}}] * 10
    )
    state = AgentLoop(settings=settings, llm_client=llm, emit=lambda _: None).run("never finishes")
    assert len(state.turns) == settings.max_iterations
    assert "iteration limit" in state.answer


def test_invoice_pipeline_produces_docx_artifact(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_asset(settings)
    invoice = {
        "invoice_no": "INV-001",
        "invoice_date": "2026-06-01",
        "due_date": "2026-06-14",
        "billing_period": "June 2026",
        "property_name": "12 Ocean St",
        "property_address": "12 Ocean St, Sydney NSW",
        "bill_to": "J. Smith",
        "items": [{"description": "Rent June", "amount": 4000}],
        "subtotal": 4000,
        "gst": 0,
        "total": 4000,
        "payment_terms": "14 days",
        "assumptions": "none",
        "business_profile": {
            "business_name": "Ocean Holdings",
            "trading_name": "Ocean Holdings",
            "abn": "12 345 678 901",
            "contact": {"email": "a@b.c", "phone": "0400 000 000"},
            "payment": {
                "method": "direct_credit",
                "account_name": "Ocean Holdings",
                "bsb": "000-000",
                "account_number": "12345678",
            },
        },
    }

    class InvoiceLLM(ScriptedLLM):
        def generate_json(self, prompt: str, provider: str = "codex") -> dict[str, Any]:
            if "invoice data generator" in prompt:
                return invoice
            return super().generate_json(prompt, provider)

    llm = InvoiceLLM(
        [
            {
                "thought": "load context",
                "action": {"tool": "read_memory", "args": {"asset_id": "12_ocean_st", "files": ["lease.md"]}},
            },
            {
                "thought": "generate invoice json",
                "action": {"tool": "generate_invoice", "args": {"context": "Rent $1000/week, tenant J. Smith"}},
            },
            {"thought": "render", "action": {"tool": "build_docx", "args": {}}},
            {"thought": "done", "final_answer": "Invoice INV-001 drafted."},
        ]
    )
    state = AgentLoop(settings=settings, llm_client=llm, emit=lambda _: None).run("Draft the June rent invoice for 12 Ocean St")

    assert len(state.artifacts) == 1
    artifact = state.artifacts[0]
    assert artifact.path.exists()
    assert artifact.path.suffix == ".docx"
    assert artifact.metadata_path is not None and artifact.metadata_path.exists()
    metadata = json.loads(artifact.metadata_path.read_text(encoding="utf-8"))
    assert metadata["asset_id"] == "12_ocean_st"
    assert "lease.md" in metadata["source_files"]


def test_research_tools_delegate_to_codex(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    llm = ScriptedLLM(
        [
            {
                "thought": "browse",
                "action": {"tool": "browse_web", "args": {"objective": "current NSW bond rates"}},
            },
            {"thought": "done", "final_answer": "ok"},
        ]
    )
    state = AgentLoop(settings=settings, llm_client=llm, emit=lambda _: None).run("research task")
    assert state.turns[0].observation.startswith("AGENTIC:")


def test_malformed_decision_is_fed_back(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    llm = ScriptedLLM(
        [
            {"thought": "forgot the action"},
            {"thought": "fixed", "final_answer": "done"},
        ]
    )
    state = AgentLoop(settings=settings, llm_client=llm, emit=lambda _: None).run("test")
    assert "must contain either final_answer or action.tool" in state.turns[0].observation
    assert state.answer == "done"


def test_empty_task_rejected(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    from src.core.errors import PMIntelligenceError

    with pytest.raises(PMIntelligenceError):
        AgentLoop(settings=settings, llm_client=ScriptedLLM([]), emit=lambda _: None).run("   ")
