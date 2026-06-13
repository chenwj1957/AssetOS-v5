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
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.agent import AgentLoop, Session
from src.agent.approval import ApprovalGate
from src.core.config import Settings, load_settings
from src.core.errors import PMIntelligenceError, UnsafeMemoryPathError
from src.memory.skills import SkillWriter

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


class ApprovalRequest(BaseModel):
    approved: bool


class ToggleRequest(BaseModel):
    enabled: bool


class SkillCreateRequest(BaseModel):
    name: str
    content: str
    summary: str = ""


def create_app(settings: Settings | None = None, loop: AgentLoop | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="AssetOS", docs_url=None, redoc_url=None)
    app.state.allow_gated = False
    app.state.chat_lock = threading.Lock()

    def approval_policy(tool_name: str, args: dict[str, Any]) -> bool:
        return bool(app.state.allow_gated)

    capabilities_path = settings.dir_data / "capabilities.json"

    def _load_capabilities() -> tuple[set[str], set[str]]:
        if capabilities_path.exists():
            try:
                data = json.loads(capabilities_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        else:
            data = {}
        return set(data.get("disabled_tools", [])), set(data.get("disabled_skills", []))

    def _save_capabilities() -> None:
        capabilities_path.parent.mkdir(parents=True, exist_ok=True)
        capabilities_path.write_text(
            json.dumps(
                {
                    "disabled_tools": sorted(app.state.disabled_tools),
                    "disabled_skills": sorted(app.state.disabled_skills),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    app.state.disabled_tools, app.state.disabled_skills = _load_capabilities()

    def tool_enabled(tool_name: str) -> bool:
        return tool_name not in app.state.disabled_tools

    def skill_enabled(skill_name: str) -> bool:
        return skill_name not in app.state.disabled_skills

    agent_loop = loop or AgentLoop(
        settings=settings,
        approval_policy=approval_policy,
        tool_enabled=tool_enabled,
        skill_enabled=skill_enabled,
    )
    if loop is not None:
        # Injected loops (tests) still respect the UI's switches.
        agent_loop.approval_policy = approval_policy
        agent_loop.tool_enabled = tool_enabled
        agent_loop.skill_enabled = skill_enabled
    session = Session(loop=agent_loop)
    app.state.session = session
    app.state.active_cancel_event = None
    app.state.active_approval_gate = None

    registry = agent_loop.memory.asset_registry
    file_registry = agent_loop.memory.file_registry
    file_writer = agent_loop.memory.file_writer
    fact_reader = agent_loop.memory.fact_reader
    schema_registry = agent_loop.memory.schema_registry
    skill_registry = agent_loop.memory.skill_registry
    skill_writer = agent_loop.memory.skill_writer

    uploads_dir = settings.dir_data / "memory" / "uploads"

    # ------------------------------------------------------------------
    # Chat (SSE: live ledger of agent activity, then the final answer)
    # ------------------------------------------------------------------

    @app.post("/api/chat")
    def chat(request: ChatRequest) -> StreamingResponse:
        message = request.message.strip()
        if not message:
            raise HTTPException(status_code=400, detail="Message cannot be empty.")

        events: "queue.Queue[dict[str, Any] | None]" = queue.Queue()
        cancel_event = threading.Event()
        approval_gate = ApprovalGate()
        app.state.active_cancel_event = cancel_event
        app.state.active_approval_gate = approval_gate

        def emit(event: dict[str, Any]) -> None:
            events.put({"type": "step", "step": event})

        def worker() -> None:
            with app.state.chat_lock:
                agent_loop.emit = emit
                try:
                    state = session.ask(message, cancel_event=cancel_event, approval_gate=approval_gate)
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
                    if app.state.active_cancel_event is cancel_event:
                        app.state.active_cancel_event = None
                    if app.state.active_approval_gate is approval_gate:
                        app.state.active_approval_gate = None
                    events.put(None)

        threading.Thread(target=worker, daemon=True).start()

        def stream() -> Iterator[str]:
            while True:
                item = events.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/api/chat/stop")
    def stop_chat() -> JSONResponse:
        cancel_event = app.state.active_cancel_event
        if cancel_event is None:
            return JSONResponse({"stopped": False})
        cancel_event.set()
        return JSONResponse({"stopped": True})

    @app.post("/api/chat/approve")
    def approve_chat(request: ApprovalRequest) -> JSONResponse:
        gate = app.state.active_approval_gate
        if gate is None:
            return JSONResponse({"ok": False})
        gate.resolve(request.approved)
        return JSONResponse({"ok": True})

    # ------------------------------------------------------------------
    # Uploads: attach a file to the conversation, optionally tagged to an asset
    # ------------------------------------------------------------------

    @app.post("/api/uploads")
    async def upload_file(file: UploadFile = File(...), asset_id: str = Form("")) -> JSONResponse:
        asset_id = asset_id.strip()
        if asset_id and asset_id not in registry.list_asset_ids():
            raise HTTPException(status_code=404, detail=f"No asset '{asset_id}'.")

        filename = Path(file.filename or "upload").name
        content = await file.read()

        if asset_id:
            try:
                file_writer.write_bytes(asset_id, f"Files/{filename}", content)
            except UnsafeMemoryPathError:
                filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
                file_writer.write_bytes(asset_id, f"Files/{filename}", content)
        else:
            uploads_dir.mkdir(parents=True, exist_ok=True)
            path = uploads_dir / filename
            if path.exists():
                filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
                path = uploads_dir / filename
            path.write_bytes(content)

        return JSONResponse({"name": filename, "asset_id": asset_id})

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
                    "stale_facts": len(fact_reader.stale_fields(asset_id)),
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
        facts_payload = fact_reader.load(asset_id)
        stale = fact_reader.stale_fields(asset_id)
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
        payload = schema_registry.load()
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

    # ------------------------------------------------------------------
    # Capabilities: enable/disable tools and skills (persisted)
    # ------------------------------------------------------------------

    @app.get("/api/capabilities")
    def get_capabilities() -> JSONResponse:
        tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "args": tool.args,
                "requires_approval": tool.requires_approval,
                "enabled": tool_enabled(tool.name),
            }
            for tool in agent_loop.tools
        ]
        skills = [
            {"name": s["name"], "summary": s["summary"], "enabled": skill_enabled(s["name"])}
            for s in skill_registry.list_available_skills()
        ]
        return JSONResponse({"tools": tools, "skills": skills})

    @app.post("/api/capabilities/tools/{name}")
    def toggle_tool(name: str, request: ToggleRequest) -> JSONResponse:
        if name not in {tool.name for tool in agent_loop.tools}:
            raise HTTPException(status_code=404, detail=f"No tool '{name}'.")
        if request.enabled:
            app.state.disabled_tools.discard(name)
        else:
            app.state.disabled_tools.add(name)
        _save_capabilities()
        return JSONResponse({"name": name, "enabled": request.enabled})

    @app.post("/api/capabilities/skills/{name}")
    def toggle_skill(name: str, request: ToggleRequest) -> JSONResponse:
        if name not in skill_registry.list_skill_names():
            raise HTTPException(status_code=404, detail=f"No skill '{name}'.")
        if request.enabled:
            app.state.disabled_skills.discard(name)
        else:
            app.state.disabled_skills.add(name)
        _save_capabilities()
        return JSONResponse({"name": name, "enabled": request.enabled})

    @app.post("/api/skills")
    def create_skill(request: SkillCreateRequest) -> JSONResponse:
        name = request.name.strip()
        content = request.content.strip()
        if not name or not content:
            raise HTTPException(status_code=400, detail="Skill name and content are required.")
        try:
            skill_dir = skill_writer.create_skill(name, content, summary=request.summary)
        except (ValueError, UnsafeMemoryPathError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return JSONResponse({"name": skill_dir.name, "enabled": skill_enabled(skill_dir.name)})

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


def main() -> None:  # pragma: no cover - manual entry point
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8400)


if __name__ == "__main__":  # pragma: no cover
    main()
