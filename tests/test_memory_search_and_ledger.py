from __future__ import annotations

from pathlib import Path
from typing import Any

from src.agent import AgentLoop
from src.memory.assets import AssetRegistry
from src.memory.facts import FactStore, SchemaStore
from src.memory.search import MemoryIndex
from tests.test_agent_loop import ScriptedLLM, make_settings, seed_asset


def make_index(settings) -> MemoryIndex:
    registry = AssetRegistry(settings=settings)
    return MemoryIndex(db_path=settings.dir_data / "memory" / "index.sqlite3", asset_registry=registry)


# ---------------------------------------------------------------------------
# Search index
# ---------------------------------------------------------------------------

def test_search_finds_content_across_assets(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_asset(settings, "12_ocean_st")
    other = settings.dir_assets / "5_harbour_rd"
    other.mkdir(parents=True)
    (other / "profile.md").write_text("# 5 Harbour Rd\nCommercial unit, owner Harbour Holdings Pty Ltd.", encoding="utf-8")

    index = make_index(settings)
    hits = index.search("Harbour Holdings owner")
    assert hits and hits[0].asset_id == "5_harbour_rd"

    # Per-asset filter.
    assert index.search("owner", asset_id="12_ocean_st") == [] or all(
        h.asset_id == "12_ocean_st" for h in index.search("owner", asset_id="12_ocean_st")
    )
    index.close()


def test_search_index_refreshes_on_change_and_delete(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_asset(settings)
    index = make_index(settings)
    assert index.refresh() >= 2  # profile + lease indexed
    assert index.refresh() == 0  # nothing changed -> no work

    lease = settings.dir_assets / "12_ocean_st" / "lease.md"
    lease.write_text("Rent: $1100/week after review. Tenant: J. Smith.", encoding="utf-8")
    assert index.search("1100 review")  # change picked up

    lease.unlink()
    index.refresh()
    assert not index.search("1100 review")  # deletion picked up
    index.close()


# ---------------------------------------------------------------------------
# Fact ledger + staleness
# ---------------------------------------------------------------------------

def test_ledger_records_changes_only_and_history_reads_back(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_asset(settings)
    schema = SchemaStore(path=settings.dir_data / "memory" / "schema.json")
    facts = FactStore(asset_registry=AssetRegistry(settings=settings), schema_store=schema)

    facts.save("12_ocean_st", {"weekly_rent": {"value": 950, "source": "lease.md"}})
    facts.save("12_ocean_st", {"weekly_rent": {"value": 950, "source": "lease.md"}})  # no change
    facts.save("12_ocean_st", {"weekly_rent": {"value": 1000, "source": "lease.md"}})  # rent review

    history = facts.history("12_ocean_st", "weekly_rent")
    assert [event["value"] for event in history] == [950, 1000]
    assert history[1]["previous_value"] == 950
    assert facts.load("12_ocean_st")["facts"]["weekly_rent"]["value"] == 1000


def test_staleness_flagged_when_source_changes(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_asset(settings)
    schema = SchemaStore(path=settings.dir_data / "memory" / "schema.json")
    facts = FactStore(asset_registry=AssetRegistry(settings=settings), schema_store=schema)

    facts.save("12_ocean_st", {"weekly_rent": {"value": 1000, "source": "lease.md"}})
    assert facts.stale_fields("12_ocean_st") == {}

    (settings.dir_assets / "12_ocean_st" / "lease.md").write_text(
        "Rent: $1100/week after review.", encoding="utf-8"
    )
    stale = facts.stale_fields("12_ocean_st")
    assert "weekly_rent" in stale
    assert "STALE" in facts.render("12_ocean_st")


def test_owner_entity_is_per_asset_in_seed_schema(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    schema = SchemaStore(path=settings.dir_data / "memory" / "schema.json")
    assert "owner_entity" in schema.active_fields()
    facts = FactStore(asset_registry=AssetRegistry(settings=settings), schema_store=schema)
    seed_asset(settings, "a_one")
    seed_asset(settings, "b_two")
    facts.save("a_one", {"owner_entity": {"value": "Alpha Pty Ltd", "source": "profile.md"}})
    facts.save("b_two", {"owner_entity": {"value": "Beta Pty Ltd", "source": "profile.md"}})
    assert facts.load("a_one")["facts"]["owner_entity"]["value"] == "Alpha Pty Ltd"
    assert facts.load("b_two")["facts"]["owner_entity"]["value"] == "Beta Pty Ltd"


# ---------------------------------------------------------------------------
# Agent-level: search-first retrieval and history tool
# ---------------------------------------------------------------------------

def test_loop_uses_search_then_history(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_asset(settings)
    schema = SchemaStore(path=settings.dir_data / "memory" / "schema.json")
    facts = FactStore(asset_registry=AssetRegistry(settings=settings), schema_store=schema)
    facts.save("12_ocean_st", {"weekly_rent": {"value": 950, "source": "lease.md"}})
    facts.save("12_ocean_st", {"weekly_rent": {"value": 1000, "source": "lease.md"}})

    llm = ScriptedLLM(
        [
            {"thought": "find the lease", "action": {"tool": "search_memory", "args": {"query": "rent Smith"}}},
            {
                "thought": "how has rent moved",
                "action": {"tool": "fact_history", "args": {"asset_id": "12_ocean_st", "field": "weekly_rent"}},
            },
            {"thought": "done", "final_answer": "Rent moved from $950 to $1000."},
        ]
    )
    state = AgentLoop(settings=settings, llm_client=llm, emit=lambda _: None).run(
        "How has the rent changed at 12 Ocean St?"
    )
    assert "lease.md" in state.turns[0].observation
    assert "950" in state.turns[1].observation and "1000" in state.turns[1].observation
