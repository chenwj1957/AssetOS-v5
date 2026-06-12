from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.agent import AgentLoop
from src.memory.assets import AssetRegistry
from src.memory.facts import FactStore, SchemaError, SchemaStore
from src.tools.calc_tool import evaluate_expression
from tests.test_agent_loop import ScriptedLLM, make_settings, seed_asset


def make_stores(tmp_path: Path):
    settings = make_settings(tmp_path)
    schema = SchemaStore(path=settings.dir_data / "memory" / "schema.json")
    facts = FactStore(asset_registry=AssetRegistry(settings=settings), schema_store=schema)
    return settings, schema, facts


# ---------------------------------------------------------------------------
# Schema morphing: expand, refine, contract, revive — with guardrails.
# ---------------------------------------------------------------------------

def test_schema_expands_contracts_and_revives(tmp_path: Path) -> None:
    _, schema, _ = make_stores(tmp_path)
    assert "weekly_rent" in schema.active_fields()

    schema.evolve(
        [{"op": "add_field", "field": "bond_amount", "type": "number", "description": "Bond held in AUD."}],
        reason="bond appears in every lease",
    )
    assert "bond_amount" in schema.active_fields()

    schema.evolve([{"op": "deprecate_field", "field": "bond_amount"}], reason="never populated")
    assert "bond_amount" not in schema.active_fields()
    assert schema.load()["fields"]["bond_amount"]["status"] == "deprecated"  # soft delete

    schema.evolve(
        [{"op": "add_field", "field": "bond_amount", "type": "number", "description": "Bond held."}],
        reason="needed again",
    )
    assert "bond_amount" in schema.active_fields()
    assert schema.load()["version"] == 4
    assert len(schema.load()["changelog"]) == 4


def test_schema_guardrails(tmp_path: Path) -> None:
    _, schema, _ = make_stores(tmp_path)
    with pytest.raises(SchemaError):  # bad type
        schema.evolve([{"op": "add_field", "field": "x_field", "type": "blob", "description": "d"}], "r")
    with pytest.raises(SchemaError):  # bad name
        schema.evolve([{"op": "add_field", "field": "Bad Name!", "type": "string", "description": "d"}], "r")
    with pytest.raises(SchemaError):  # revive with different type
        schema.evolve([{"op": "deprecate_field", "field": "weekly_rent"}], "r")
        schema.evolve([{"op": "add_field", "field": "weekly_rent", "type": "string", "description": "d"}], "r")
    with pytest.raises(SchemaError):  # unknown op
        schema.evolve([{"op": "drop_table", "field": "weekly_rent"}], "r")


def test_fact_validation_and_unknown_field_feedback(tmp_path: Path) -> None:
    settings, schema, facts = make_stores(tmp_path)
    seed_asset(settings)
    saved, rejected = facts.save(
        "12_ocean_st",
        {
            "weekly_rent": {"value": 1000, "source": "lease.md"},
            "lease_end_date": {"value": "not-a-date", "source": "lease.md"},
            "mystery_field": {"value": "x", "source": "lease.md"},
        },
    )
    assert saved["facts"]["weekly_rent"]["value"] == 1000
    assert "lease_end_date" not in saved["facts"]
    assert any("YYYY-MM-DD" in r for r in rejected)
    assert any("mystery_field" in r and "evolve_schema" in r for r in rejected)

    # Deprecated fields keep their data, flagged on render.
    schema.evolve([{"op": "deprecate_field", "field": "weekly_rent"}], "test")
    assert "[field deprecated]" in facts.render("12_ocean_st")


# ---------------------------------------------------------------------------
# End-to-end: the agent grows the schema mid-run, then uses calculate.
# ---------------------------------------------------------------------------

def test_loop_morphs_schema_then_calculates(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_asset(settings)

    class ExtractingLLM(ScriptedLLM):
        def generate_json(self, prompt: str, provider: str = "codex") -> dict[str, Any]:
            if "Extract facts" in prompt:
                base = {"weekly_rent": {"value": 1000, "source": "lease.md"}}
                if "bond_amount" in prompt:  # schema now includes the new field
                    base["bond_amount"] = {"value": 4000, "source": "lease.md"}
                else:
                    base["unschema_candidates"] = [
                        {"field": "bond_amount", "type": "number", "description": "Bond held in AUD."}
                    ]
                return base
            return super().generate_json(prompt, provider)

    llm = ExtractingLLM(
        [
            {"thought": "derive facts", "action": {"tool": "extract_facts", "args": {"asset_id": "12_ocean_st"}}},
            {
                "thought": "bond keeps appearing; give it a home",
                "action": {
                    "tool": "evolve_schema",
                    "args": {
                        "operations": [
                            {"op": "add_field", "field": "bond_amount", "type": "number", "description": "Bond held in AUD."}
                        ],
                        "reason": "extraction surfaced bond_amount as a recurring fact",
                    },
                },
            },
            {"thought": "re-extract with new field", "action": {"tool": "extract_facts", "args": {"asset_id": "12_ocean_st"}}},
            {"thought": "monthly rent", "action": {"tool": "calculate", "args": {"expression": "round(1000 * 52 / 12, 2)"}}},
            {"thought": "done", "final_answer": "Monthly rent is $4,333.33; bond $4,000 now tracked."},
        ]
    )
    state = AgentLoop(settings=settings, llm_client=llm, emit=lambda _: None).run(
        "What is the monthly rent at 12 Ocean St, and track the bond."
    )
    assert "bond_amount" in state.turns[0].observation  # surfaced as candidate
    assert "Schema evolved to v2" in state.turns[1].observation
    assert "bond_amount = 4000" in state.turns[2].observation
    assert "4333.33" in state.turns[3].observation
    assert state.answer.startswith("Monthly rent")


# ---------------------------------------------------------------------------
# calculate: correct and locked down.
# ---------------------------------------------------------------------------

def test_calculate_arithmetic() -> None:
    assert evaluate_expression("round(1000 * 52 / 12, 2)") == 4333.33
    assert evaluate_expression("sum(100, 200, 300) * 1.1") == pytest.approx(660.0)
    assert evaluate_expression("max(0, -5)") == 0


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('ls')",
        "open('/etc/passwd')",
        "(1).__class__",
        "[1,2][0]",
        "x + 1",
        "round(1, ndigits=2)",
    ],
)
def test_calculate_rejects_non_arithmetic(expression: str) -> None:
    with pytest.raises(ValueError):
        evaluate_expression(expression)
