from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from front_end.server import create_app
from src.agent import AgentLoop
from src.memory.assets import AssetRegistry
from src.memory.facts import FactStore, SchemaStore
from tests.test_agent_loop import ScriptedLLM, make_settings, seed_asset


def make_client(tmp_path: Path, llm: ScriptedLLM) -> TestClient:
    settings = make_settings(tmp_path)
    seed_asset(settings)
    loop = AgentLoop(settings=settings, llm_client=llm, emit=lambda _: None)
    return TestClient(create_app(settings=settings, loop=loop))


def parse_sse(text: str) -> list[dict]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def test_chat_streams_events_then_final_answer(tmp_path: Path) -> None:
    llm = ScriptedLLM(
        [
            {"thought": "read", "action": {"tool": "read_memory", "args": {"asset_id": "12_ocean_st", "files": ["lease.md"]}}},
            {"thought": "done", "final_answer": "Weekly rent is $1000."},
        ]
    )
    client = make_client(tmp_path, llm)
    response = client.post("/api/chat", json={"message": "What is the rent?"})
    assert response.status_code == 200
    events = parse_sse(response.text)
    assert any(e["type"] == "event" and "read_memory" in e["text"] for e in events)
    final = [e for e in events if e["type"] == "final"]
    assert final and final[0]["answer"] == "Weekly rent is $1000."
    assert final[0]["asset"] == "12_ocean_st"


def test_assets_endpoints_and_safe_paths(tmp_path: Path) -> None:
    client = make_client(tmp_path, ScriptedLLM([]))
    assets = client.get("/api/assets").json()["assets"]
    assert assets[0]["id"] == "12_ocean_st"

    detail = client.get("/api/assets/12_ocean_st").json()
    assert any(f["name"] == "lease.md" for f in detail["files"])

    content = client.get("/api/assets/12_ocean_st/files/lease.md").json()
    assert "Rent" in content["content"]

    # Path traversal is rejected, not served.
    bad = client.get("/api/assets/12_ocean_st/files/../../../etc/passwd")
    assert bad.status_code in {400, 404}


def test_facts_with_stale_flag_surface_in_vault(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_asset(settings)
    schema = SchemaStore(path=settings.dir_data / "memory" / "schema.json")
    facts = FactStore(asset_registry=AssetRegistry(settings=settings), schema_store=schema)
    facts.save("12_ocean_st", {"weekly_rent": {"value": 1000, "source": "lease.md"}})
    (settings.dir_assets / "12_ocean_st" / "lease.md").write_text("Rent: $1100/week.", encoding="utf-8")

    loop = AgentLoop(settings=settings, llm_client=ScriptedLLM([]), emit=lambda _: None)
    client = TestClient(create_app(settings=settings, loop=loop))
    detail = client.get("/api/assets/12_ocean_st").json()
    rent = next(f for f in detail["facts"] if f["field"] == "weekly_rent")
    assert rent["value"] == 1000 and rent["stale"] is True
    assert client.get("/api/assets").json()["assets"][0]["stale_facts"] == 1


def test_gated_switch_controls_approval_policy(tmp_path: Path) -> None:
    def gated() -> ScriptedLLM:
        return ScriptedLLM(
            [
                {"thought": "delegate", "action": {"tool": "codex_agent", "args": {"task": "x"}}},
                {"thought": "done", "final_answer": "ok"},
            ]
        )

    client = make_client(tmp_path, gated())
    events = parse_sse(client.post("/api/chat", json={"message": "tidy"}).text)
    assert any("DENIED" in e.get("text", "") for e in events if e["type"] == "event")

    client.post("/api/settings", json={"allow_gated": True})
    assert client.get("/api/settings").json()["allow_gated"] is True
    # Re-arm the scripted LLM for a second run on the same app/session.
    client.app.state.session.loop.llm_client = gated()
    events = parse_sse(client.post("/api/chat", json={"message": "tidy again"}).text)
    assert not any("DENIED" in e.get("text", "") for e in events)


def test_workflows_and_runs_endpoints(tmp_path: Path) -> None:
    llm = ScriptedLLM([{"thought": "done", "final_answer": "Done."}])
    client = make_client(tmp_path, llm)

    workflows = client.get("/api/workflows").json()["workflows"]
    assert any(w["name"] == "Arrears sweep" for w in workflows)
    client.post("/api/workflows", json={"name": "My check", "task": "Check things."})
    assert any(w["name"] == "My check" for w in client.get("/api/workflows").json()["workflows"])

    # A chat run produces a journal entry that the Runs view can read.
    client.post("/api/chat", json={"message": "general question"})
    runs = client.get("/api/runs").json()["runs"]
    assert runs and runs[0]["task"] == "general question"
    detail = client.get(f"/api/runs/{runs[0]['asset']}/{runs[0]['name']}")
    assert detail.status_code == 200
    assert "general question" in detail.json()["content"]
