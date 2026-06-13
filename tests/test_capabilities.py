from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from front_end.server import create_app
from src.agent import AgentLoop
from src.core.config import Settings
from tests.test_agent_loop import ScriptedLLM, make_settings, seed_asset


def seed_skill(settings: Settings, name: str = "rent_review", summary: str = "How to review rent.") -> None:
    skill_dir = settings.dir_skills / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.md").write_text("# Rent review\nSteps...", encoding="utf-8")
    (skill_dir / "skill.json").write_text(json.dumps({"summary": summary}), encoding="utf-8")


def make_client(settings: Settings, llm: ScriptedLLM) -> TestClient:
    loop = AgentLoop(settings=settings, llm_client=llm, emit=lambda _: None)
    return TestClient(create_app(settings=settings, loop=loop))


def test_capabilities_lists_tools_and_skills_enabled_by_default(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_asset(settings)
    seed_skill(settings)
    client = make_client(settings, ScriptedLLM([]))

    payload = client.get("/api/capabilities").json()
    assert any(t["name"] == "codex_agent" and t["enabled"] for t in payload["tools"])
    assert any(s["name"] == "rent_review" and s["enabled"] for s in payload["skills"])


def test_toggling_a_tool_persists_and_disables_it_in_the_loop(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_asset(settings)

    llm = ScriptedLLM(
        [
            {"thought": "try", "action": {"tool": "list_skills", "args": {}}},
            {"thought": "done", "final_answer": "ok"},
        ]
    )
    client = make_client(settings, llm)

    resp = client.post("/api/capabilities/tools/list_skills", json={"enabled": False})
    assert resp.status_code == 200
    assert resp.json() == {"name": "list_skills", "enabled": False}

    # Persisted to disk.
    capabilities = json.loads((settings.dir_data / "capabilities.json").read_text(encoding="utf-8"))
    assert capabilities["disabled_tools"] == ["list_skills"]

    state = client.app.state.session.loop.run("try something")
    assert "disabled by the user" in state.turns[0].observation

    # Reflected back in /api/capabilities.
    payload = client.get("/api/capabilities").json()
    assert not any(t["name"] == "list_skills" and t["enabled"] for t in payload["tools"])


def test_toggling_a_skill_disables_load_skill(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_asset(settings)
    seed_skill(settings)

    llm = ScriptedLLM(
        [
            {"thought": "load", "action": {"tool": "load_skill", "args": {"name": "rent_review"}}},
            {"thought": "done", "final_answer": "ok"},
        ]
    )
    client = make_client(settings, llm)

    resp = client.post("/api/capabilities/skills/rent_review", json={"enabled": False})
    assert resp.status_code == 200

    state = client.app.state.session.loop.run("try something")
    assert "disabled by the user" in state.turns[0].observation


def test_create_skill_via_api(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_asset(settings)
    client = make_client(settings, ScriptedLLM([]))

    resp = client.post(
        "/api/skills",
        json={"name": "Lease Renewal", "content": "# Lease Renewal\nDo X then Y.", "summary": "Renew a lease."},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Lease_Renewal"

    payload = client.get("/api/capabilities").json()
    skill = next(s for s in payload["skills"] if s["name"] == "Lease_Renewal")
    assert skill["enabled"] is True
    assert skill["summary"] == "Renew a lease."

    assert (settings.dir_skills / "Lease_Renewal" / "skill.md").read_text(encoding="utf-8").startswith("# Lease Renewal")


def test_toggle_unknown_tool_returns_404(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_asset(settings)
    client = make_client(settings, ScriptedLLM([]))

    resp = client.post("/api/capabilities/tools/nope", json={"enabled": False})
    assert resp.status_code == 404
