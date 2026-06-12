from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.types import ArtifactResult
from src.memory.files.writer import FileWriter
from src.tools.build_docx.builder import DocxBuilder
from src.tools.build_docx.mappers.invoice_to_docx_spec import invoice_to_docx_spec
from src.tools.build_docx.schema.docx_spec import DocxSpec
from src.tools.build_docx.validators import (
    validate_docx_spec,
    validate_input_json_path,
    validate_invoice_payload,
    validate_mode,
    validate_output_docx_path,
)


def build_invoice_docx_artifact(
    invoice: dict[str, Any],
    asset_id: str,
    file_writer: FileWriter,
    *,
    source_files: Sequence[str] = (),
    selected_skills: Sequence[str] = (),
    layout: str = "classic_tax_invoice",
) -> ArtifactResult:
    spec = invoice_to_docx_spec(invoice, layout=layout)
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / "invoice.docx"
        DocxBuilder().build(spec, temp_path)
        docx_bytes = temp_path.read_bytes()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{timestamp}_invoice_draft").strip("._") or "artifact"
    relative_path = f"Artifact/{file_stem}.docx"
    path = file_writer.write_bytes(asset_id, relative_path, docx_bytes)
    metadata_path = file_writer.write_json(
        asset_id,
        f"{relative_path}.meta.json",
        {
            "artifact_type": "invoice_docx",
            "asset_id": asset_id,
            "source_files": list(source_files),
            "selected_skills": list(selected_skills),
            "document_type": "invoice",
            "docx_spec": spec.to_dict(),
            "status": "draft",
            "created_at": timestamp,
        },
    )
    return ArtifactResult(artifact_type="invoice_docx", path=path, metadata_path=metadata_path)


def run_build_docx_tool(payload: dict[str, Any]) -> dict[str, Any]:
    output_docx_path = Path(str(payload.get("output_docx_path", "")))
    docx_spec_path: Path | None = None
    try:
        mode = str(payload.get("mode", ""))
        validate_mode(mode)
        input_json_path = Path(str(payload.get("input_json_path", "")))
        validate_input_json_path(input_json_path)
        validate_output_docx_path(output_docx_path)

        input_payload = _load_json(input_json_path)
        if mode == "from_docx_spec":
            spec = DocxSpec.from_dict(input_payload)
        else:
            validate_invoice_payload(input_payload)
            spec = invoice_to_docx_spec(
                input_payload,
                layout=str(payload.get("layout", "classic_tax_invoice")),
            )
            save_docx_spec_path = payload.get("save_docx_spec_path")
            if save_docx_spec_path:
                docx_spec_path = Path(str(save_docx_spec_path))
                docx_spec_path.parent.mkdir(parents=True, exist_ok=True)
                docx_spec_path.write_text(json.dumps(spec.to_dict(), indent=2), encoding="utf-8")

        validate_docx_spec(spec)
        DocxBuilder().build(spec, output_docx_path)
        return {
            "status": "success",
            "output_docx_path": str(output_docx_path),
            "docx_spec_path": str(docx_spec_path) if docx_spec_path is not None else None,
            "error": None,
        }
    except Exception as exc:
        return {
            "status": "error",
            "output_docx_path": str(output_docx_path),
            "docx_spec_path": None,
            "error": str(exc),
        }


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload
