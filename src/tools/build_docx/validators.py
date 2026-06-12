from __future__ import annotations

from pathlib import Path
from typing import Any

from src.tools.build_docx.schema.docx_spec import DocxSpec


VALID_MODES = {"from_docx_spec", "from_invoice_data"}


def validate_output_docx_path(output_path: Path) -> None:
    if output_path.suffix.lower() != ".docx":
        raise ValueError("Output path must end with .docx.")


def validate_input_json_path(input_json_path: Path) -> None:
    if not input_json_path.exists():
        raise FileNotFoundError(f"Input JSON does not exist: {input_json_path}")


def validate_mode(mode: str) -> None:
    if mode not in VALID_MODES:
        raise ValueError(f"Mode must be one of: {', '.join(sorted(VALID_MODES))}.")


def validate_invoice_payload(invoice: dict[str, Any]) -> None:
    items = invoice.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("Invoice mode requires at least one invoice item.")


def validate_docx_spec(spec: DocxSpec) -> None:
    if not spec.blocks:
        raise ValueError("DocxSpec must contain at least one block.")
