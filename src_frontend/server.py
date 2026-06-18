"""AssetOS web interface server.

Completely separate from the agent core: this module imports ``src_backend``;
nothing in ``src_backend`` knows this exists. Delete ``src_frontend/`` and the
agent, CLI, and scheduler are untouched.

Run:  python -m src_frontend.server   (serves http://localhost:8400)
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

from src_backend.agent import AgentLoop, CapabilitiesStore, Session, WorkflowStore
from src_backend.agent.approval import ApprovalGate
from src_backend.agent.journal import global_run_path, list_runs
from src_backend.core.config import Settings, load_settings
from src_backend.core.constants import ALLOWED_MEMORY_EXTENSIONS
from src_backend.core.errors import BaseAppError, UnsafeMemoryPathError
from src_backend.memory.files.editor.docx.preview import docx_to_html
from src_backend.memory.files.upload import FileUploader
from src_backend.memory.skills import SkillWriter
from src_backend.tools.artifact_tools import ARTIFACT_TOOLS
from src_backend.tools.calc_tool import CALC_TOOLS
from src_backend.tools.fact_tools import FACT_TOOLS
from src_backend.tools.memory_tools import MEMORY_TOOLS
from src_backend.tools.research_tools import RESEARCH_TOOLS

STATIC_DIR = Path(__file__).parent / "static"

TOOL_GROUPS: dict[str, str] = {
    **{tool.name: "Memory" for tool in MEMORY_TOOLS},
    **{tool.name: "Facts" for tool in FACT_TOOLS},
    **{tool.name: "Calculations" for tool in CALC_TOOLS},
    **{tool.name: "Research" for tool in RESEARCH_TOOLS},
    **{tool.name: "Artifacts" for tool in ARTIFACT_TOOLS},
}
class ChatRequest(BaseModel):
    message: str
    attachments: list[str] = []


class SettingsRequest(BaseModel):
    allow_gated: bool


class WorkflowRequest(BaseModel):
    name: str
    task: str
    type: str = "custom"


class ApprovalRequest(BaseModel):
    approved: bool


class AssignUploadRequest(BaseModel):
    name: str
    asset_id: str


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

    capabilities = CapabilitiesStore(settings.dir_data / "capabilities.json")

    agent_loop = loop or AgentLoop(
        settings=settings,
        approval_policy=approval_policy,
        tool_enabled=capabilities.tool_enabled,
        skill_enabled=capabilities.skill_enabled,
    )
    if loop is not None:
        # Injected loops (tests) still respect the UI's switches.
        agent_loop.approval_policy = approval_policy
        agent_loop.tool_enabled = capabilities.tool_enabled
        agent_loop.skill_enabled = capabilities.skill_enabled
    session = Session(loop=agent_loop)
    app.state.session = session
    app.state.active_cancel_event = None
    app.state.active_approval_gate = None

    registry = agent_loop.memory.asset_registry
    file_registry = agent_loop.memory.file_registry
    fact_reader = agent_loop.memory.fact_reader
    schema_registry = agent_loop.memory.schema_registry
    skill_registry = agent_loop.memory.skill_registry
    skill_writer = agent_loop.memory.skill_writer

    uploads_dir = settings.dir_data / "memory" / "uploads"
    upload_service = FileUploader(
        file_writer=agent_loop.memory.file_writer,
        asset_registry=registry,
        llm_client=agent_loop.llm_client,
        uploads_dir=uploads_dir,
    )

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
                    if state.selected_asset:
                        for name in request.attachments:
                            upload_service.assign(name, state.selected_asset)
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
                except BaseAppError as exc:
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
            filename = upload_service.save_to_asset(asset_id, filename, content)
        else:
            filename = upload_service.save_generic(filename, content)

        return JSONResponse({"name": filename, "asset_id": asset_id})

    @app.post("/api/uploads/assign")
    def assign_upload(request: AssignUploadRequest) -> JSONResponse:
        """Move a previously-uploaded generic file into an asset's Files/ folder,
        for when the asset was selected after the file was attached."""
        asset_id = request.asset_id.strip()
        if asset_id not in registry.list_asset_ids():
            raise HTTPException(status_code=404, detail=f"No asset '{asset_id}'.")

        filename = upload_service.assign(request.name, asset_id)
        if filename is None:
            raise HTTPException(status_code=404, detail=f"Upload '{request.name}' not found.")

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
            for f in file_registry.list_all_files_by_asset(asset_id)
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
        artifacts = file_registry.list_artifacts_by_asset(asset_id)
        runs = file_registry.list_run_names(asset_id)
        has_profile = (asset_dir / "profile.md").is_file()
        return JSONResponse(
            {
                "id": asset_id,
                "files": files,
                "facts": facts,
                "artifacts": artifacts,
                "runs": runs,
                "has_profile": has_profile,
            }
        )

    @app.get("/api/assets/{asset_id}/files/{file_name:path}/preview")
    def preview_asset_file(asset_id: str, file_name: str) -> JSONResponse:
        try:
            path = file_registry.resolve_safe_file_path(asset_id, f"Files/{file_name}")
        except UnsafeMemoryPathError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not path.exists():
            raise HTTPException(status_code=404, detail="File not found.")
        if path.suffix.lower() != ".docx":
            raise HTTPException(status_code=415, detail="Preview is only available for .docx files.")
        return JSONResponse({"name": file_name, "html": docx_to_html(path)})

    @app.get("/api/assets/{asset_id}/files/{file_name:path}/view")
    def view_asset_file(asset_id: str, file_name: str) -> FileResponse:
        try:
            path = file_registry.resolve_safe_file_path(asset_id, f"Files/{file_name}")
        except UnsafeMemoryPathError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="File not found.")
        return FileResponse(path, content_disposition_type="inline")

    @app.get("/api/assets/{asset_id}/files/{file_name:path}")
    def asset_file(asset_id: str, file_name: str) -> JSONResponse:
        try:
            path = file_registry.resolve_safe_file_path(asset_id, f"Files/{file_name}")
        except UnsafeMemoryPathError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not path.exists() or path.suffix.lower() not in ALLOWED_MEMORY_EXTENSIONS:
            raise HTTPException(status_code=404, detail="File not found.")
        return JSONResponse({"name": file_name, "content": path.read_text(encoding="utf-8")})

    @app.get("/api/assets/{asset_id}/download/{file_name:path}")
    def download_asset_file(asset_id: str, file_name: str) -> FileResponse:
        try:
            path = file_registry.resolve_safe_file_path(asset_id, f"Files/{file_name}")
        except UnsafeMemoryPathError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="File not found.")
        return FileResponse(path, filename=path.name)

    @app.get("/api/assets/{asset_id}/artifacts/{name}")
    def download_artifact(asset_id: str, name: str) -> FileResponse:
        try:
            path = file_registry.resolve_safe_file_path(asset_id, f"Artifact/{name}")
        except UnsafeMemoryPathError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not path.exists():
            raise HTTPException(status_code=404, detail="Artifact not found.")
        return FileResponse(path, filename=name)

    @app.get("/api/assets/{asset_id}/artifacts/{name}/preview")
    def preview_artifact(asset_id: str, name: str) -> JSONResponse:
        try:
            path = file_registry.resolve_safe_file_path(asset_id, f"Artifact/{name}")
        except UnsafeMemoryPathError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not path.exists():
            raise HTTPException(status_code=404, detail="Artifact not found.")
        if path.suffix.lower() != ".docx":
            raise HTTPException(status_code=415, detail="Preview is only available for .docx artifacts.")
        return JSONResponse({"name": name, "html": docx_to_html(path)})

    @app.get("/api/assets/{asset_id}/{file_name:path}")
    def asset_root_file(asset_id: str, file_name: str) -> JSONResponse:
        try:
            path = file_registry.resolve_safe_file_path(asset_id, file_name)
        except UnsafeMemoryPathError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not path.exists() or path.suffix.lower() not in ALLOWED_MEMORY_EXTENSIONS:
            raise HTTPException(status_code=404, detail="File not found.")
        return JSONResponse({"name": file_name, "content": path.read_text(encoding="utf-8")})

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
    def list_runs_endpoint() -> JSONResponse:
        runs = list_runs(settings, registry.list_asset_ids())
        return JSONResponse(
            {"runs": [{"asset": r.asset_id, "name": r.name, "task": r.task} for r in runs]}
        )

    @app.get("/api/runs/{asset_id}/{name}")
    @app.get("/api/runs//{name}")
    def run_detail(name: str, asset_id: str = "") -> JSONResponse:
        if asset_id:
            try:
                path = file_registry.resolve_safe_file_path(asset_id, f"runs/{name}")
            except UnsafeMemoryPathError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
        else:
            try:
                path = global_run_path(settings, name)
            except UnsafeMemoryPathError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
        if not path.exists():
            raise HTTPException(status_code=404, detail="Run not found.")
        return JSONResponse({"name": name, "content": path.read_text(encoding="utf-8")})

    # ------------------------------------------------------------------
    # Workflows (saved task presets) + settings
    # ------------------------------------------------------------------

    workflow_store = WorkflowStore(settings.dir_data / "workflows.json")

    @app.get("/api/workflows")
    def get_workflows() -> JSONResponse:
        return JSONResponse({"workflows": workflow_store.load()})

    @app.post("/api/workflows")
    def add_workflow(request: WorkflowRequest) -> JSONResponse:
        workflows = workflow_store.add(request.name.strip(), request.task.strip(), request.type.strip() or "custom")
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
                "enabled": capabilities.tool_enabled(tool.name),
                "group": TOOL_GROUPS.get(tool.name, "Other"),
            }
            for tool in agent_loop.tools
        ]
        skills = [
            {"name": s["name"], "summary": s["summary"], "enabled": capabilities.skill_enabled(s["name"])}
            for s in skill_registry.list_available_skills()
        ]
        return JSONResponse({"tools": tools, "skills": skills})

    @app.post("/api/capabilities/tools/{name}")
    def toggle_tool(name: str, request: ToggleRequest) -> JSONResponse:
        if name not in {tool.name for tool in agent_loop.tools}:
            raise HTTPException(status_code=404, detail=f"No tool '{name}'.")
        capabilities.set_tool_enabled(name, request.enabled)
        return JSONResponse({"name": name, "enabled": request.enabled})

    @app.post("/api/capabilities/skills/{name}")
    def toggle_skill(name: str, request: ToggleRequest) -> JSONResponse:
        if name not in skill_registry.list_skill_names():
            raise HTTPException(status_code=404, detail=f"No skill '{name}'.")
        capabilities.set_skill_enabled(name, request.enabled)
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
        return JSONResponse({"name": skill_dir.name, "enabled": capabilities.skill_enabled(skill_dir.name)})

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


def main() -> None:  # pragma: no cover - manual entry point
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8400)


if __name__ == "__main__":  # pragma: no cover
    main()
