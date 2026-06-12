"""AssetOS web interface server.

Completely separate from the agent core: this module imports ``src``;
nothing in ``src`` knows this exists. Delete ``front_end/`` and the
agent, CLI, and scheduler are untouched.

Run:  python -m front_end.server   (serves http://localhost:8400)
"""
from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.agent import AgentLoop, Session
from src.core.config import Settings, load_settings
from src.core.errors import PMIntelligenceError, UnsafeMemoryPathError

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_WORKFLOWS = [
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


class ChatRequest(BaseModel):
    message: str


class SettingsRequest(BaseModel):
    allow_gated: bool


class WorkflowRequest(BaseModel):
    name: str
    task: str


def create_app(settings: Settings | None = None, loop: AgentLoop | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="AssetOS", docs_url=None, redoc_url=None)
    app.state.allow_gated = False
    app.state.chat_lock = threading.Lock()

    def approval_policy(tool_name: str, args: dict[str, Any]) -> bool:
        return bool(app.state.allow_gated)

    agent_loop = loop or AgentLoop(settings=settings, approval_policy=approval_policy)
    if loop is not None:
        # Injected loops (tests) still respect the UI's gated-tools switch.
        agent_loop.approval_policy = approval_policy
    session = Session(loop=agent_loop)
    app.state.session = session

    registry = agent_loop._wiring["asset_registry"]
    file_registry = agent_loop._wiring["file_registry"]
    fact_store = agent_loop._wiring["fact_store"]
    schema_store = agent_loop._wiring["schema_store"]

    # ------------------------------------------------------------------
    # Chat (SSE: live ledger of agent activity, then the final answer)
    # ------------------------------------------------------------------

    @app.post("/api/chat")
    def chat(request: ChatRequest) -> StreamingResponse:
        message = request.message.strip()
        if not message:
            raise HTTPException(status_code=400, detail="Message cannot be empty.")

        events: "queue.Queue[dict[str, Any] | None]" = queue.Queue()

        def emit(text: str) -> None:
            events.put({"type": "event", "text": text})

        def worker() -> None:
            with app.state.chat_lock:
                agent_loop.emit = emit
                try:
                    state = session.ask(message)
                    events.put(
                        {
                            "type": "final",
                            "answer": str(state.answer),
                            "asset": state.selected_asset,
                            "artifacts": [
                                {
                                    "type": artifact.artifact_type,
                                    "name": artifact.path.name,
                                    "asset": state.selected_asset,
                                }
                                for artifact in state.artifacts
                            ],
                            "turns": [
                                {"tool": turn.tool, "thought": turn.thought}
                                for turn in state.turns
                            ],
                        }
                    )
                except PMIntelligenceError as exc:
                    events.put({"type": "error", "text": str(exc)})
                finally:
                    events.put(None)

        threading.Thread(target=worker, daemon=True).start()

        def stream() -> Iterator[str]:
            while True:
                item = events.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    # ------------------------------------------------------------------
    # Vault: assets, facts, files, artifacts
    # ------------------------------------------------------------------

    @app.get("/api/assets")
    def list_assets() -> JSONResponse:
        profiles = registry.list_asset_profiles()
        assets = []
        for asset_id in registry.list_asset_ids():
            files = file_registry.list_files_by_asset(asset_id)
            profile = " ".join(profiles.get(asset_id, "").split())
            assets.append(
                {
                    "id": asset_id,
                    "profile": profile[:240],
                    "file_count": len(files),
                    "stale_facts": len(fact_store.stale_fields(asset_id)),
                }
            )
        return JSONResponse({"assets": assets})

    @app.get("/api/assets/{asset_id}")
    def asset_detail(asset_id: str) -> JSONResponse:
        if asset_id not in registry.list_asset_ids():
            raise HTTPException(status_code=404, detail=f"No asset '{asset_id}'.")
        asset_dir = registry.resolve_asset_dir(asset_id)
        files = [
            {"name": f.file_name, "summary": f.summary}
            for f in file_registry.list_files_by_asset(asset_id)
        ]
        facts_payload = fact_store.load(asset_id)
        stale = fact_store.stale_fields(asset_id)
        facts = [
            {
                "field": name,
                "value": entry.get("value"),
                "source": entry.get("source"),
                "stale": name in stale,
            }
            for name, entry in sorted(facts_payload.get("facts", {}).items())
        ]
        artifact_dir = asset_dir / "Artifact"
        artifacts = (
            sorted(p.name for p in artifact_dir.iterdir() if p.is_file() and p.suffix == ".docx")
            if artifact_dir.exists()
            else []
        )
        return JSONResponse(
            {"id": asset_id, "files": files, "facts": facts, "artifacts": artifacts}
        )

    @app.get("/api/assets/{asset_id}/files/{file_name:path}")
    def asset_file(asset_id: str, file_name: str) -> JSONResponse:
        try:
            path = file_registry.resolve_safe_file_path(asset_id, file_name)
        except UnsafeMemoryPathError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not path.exists() or path.suffix.lower() not in {".md", ".txt"}:
            raise HTTPException(status_code=404, detail="File not found.")
        return JSONResponse({"name": file_name, "content": path.read_text(encoding="utf-8")})

    @app.get("/api/assets/{asset_id}/artifacts/{name}")
    def download_artifact(asset_id: str, name: str) -> FileResponse:
        try:
            path = file_registry.resolve_safe_file_path(asset_id, f"Artifact/{name}")
        except UnsafeMemoryPathError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not path.exists():
            raise HTTPException(status_code=404, detail="Artifact not found.")
        return FileResponse(path, filename=name)

    @app.get("/api/schema")
    def schema() -> JSONResponse:
        payload = schema_store.load()
        return JSONResponse(
            {
                "version": payload["version"],
                "fields": [
                    {"name": name, **{k: spec[k] for k in ("type", "description", "status")}}
                    for name, spec in sorted(payload["fields"].items())
                ],
            }
        )

    # ------------------------------------------------------------------
    # Runs (journals)
    # ------------------------------------------------------------------

    @app.get("/api/runs")
    def list_runs() -> JSONResponse:
        runs: list[dict[str, str]] = []
        scopes = [(asset_id, registry.resolve_asset_dir(asset_id) / "runs") for asset_id in registry.list_asset_ids()]
        scopes.append(("", settings.dir_data / "memory" / "runs"))
        for asset_id, runs_dir in scopes:
            if not runs_dir.exists():
                continue
            for path in runs_dir.glob("*.md"):
                first_lines = path.read_text(encoding="utf-8").splitlines()
                task = next((l[6:] for l in first_lines if l.startswith("Task: ")), "")
                runs.append({"asset": asset_id, "name": path.name, "task": task})
        runs.sort(key=lambda r: r["name"], reverse=True)
        return JSONResponse({"runs": runs[:100]})

    @app.get("/api/runs/{asset_id}/{name}")
    @app.get("/api/runs//{name}")
    def run_detail(name: str, asset_id: str = "") -> JSONResponse:
        if asset_id:
            try:
                path = file_registry.resolve_safe_file_path(asset_id, f"runs/{name}")
            except UnsafeMemoryPathError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
        else:
            if "/" in name or ".." in name:
                raise HTTPException(status_code=400, detail="Invalid run name.")
            path = settings.dir_data / "memory" / "runs" / name
        if not path.exists():
            raise HTTPException(status_code=404, detail="Run not found.")
        return JSONResponse({"name": name, "content": path.read_text(encoding="utf-8")})

    # ------------------------------------------------------------------
    # Workflows (saved task presets) + settings
    # ------------------------------------------------------------------

    workflows_path = settings.dir_data / "workflows.json"

    def load_workflows() -> list[dict[str, str]]:
        if not workflows_path.exists():
            workflows_path.parent.mkdir(parents=True, exist_ok=True)
            workflows_path.write_text(json.dumps({"workflows": DEFAULT_WORKFLOWS}, indent=2), encoding="utf-8")
        return json.loads(workflows_path.read_text(encoding="utf-8")).get("workflows", [])

    @app.get("/api/workflows")
    def get_workflows() -> JSONResponse:
        return JSONResponse({"workflows": load_workflows()})

    @app.post("/api/workflows")
    def add_workflow(request: WorkflowRequest) -> JSONResponse:
        workflows = load_workflows()
        workflows.append({"name": request.name.strip(), "task": request.task.strip()})
        workflows_path.write_text(json.dumps({"workflows": workflows}, indent=2), encoding="utf-8")
        return JSONResponse({"workflows": workflows})

    @app.get("/api/settings")
    def get_settings() -> JSONResponse:
        return JSONResponse({"allow_gated": bool(app.state.allow_gated)})

    @app.post("/api/settings")
    def update_settings(request: SettingsRequest) -> JSONResponse:
        app.state.allow_gated = request.allow_gated
        return JSONResponse({"allow_gated": bool(app.state.allow_gated)})

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


def main() -> None:  # pragma: no cover - manual entry point
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8400)


if __name__ == "__main__":  # pragma: no cover
    main()
