from __future__ import annotations

from typing import Any

from src.core.errors import RoutingError
from src.tools.base import ToolContext, ToolResult, ToolSpec, require_str
from src.tools.build_docx.schema.invoice import validate_invoice_data
from src.tools.build_docx.tool import build_invoice_docx_artifact

INVOICE_FIELDS = (
    "invoice_no, invoice_date, due_date, billing_period, property_name, property_address, "
    "bill_to, items, subtotal, gst, total, payment_terms, assumptions, business_profile"
)


def _invoice_prompt(context_text: str, validation_error: str | None = None) -> str:
    feedback = f"Previous output was invalid: {validation_error}\n" if validation_error else ""
    return (
        "Return only valid JSON. No markdown, no prose, no comments.\n"
        "You are the AssetOS invoice data generator. Use the supplied context to produce "
        "structured invoice JSON for DOCX rendering.\n"
        f"{feedback}"
        f"Return JSON with exactly these fields: {INVOICE_FIELDS}.\n"
        "business_profile must be an object with business_name, trading_name, abn, contact, and payment. "
        "contact must include email and phone. payment must include method, account_name, bsb, and account_number. "
        "Use method value direct_credit when bank details are available.\n"
        "items must be a non-empty list of objects with description and amount.\n"
        "Use 'To be confirmed' for unknown values. Do not invent facts not in the supplied context.\n\n"
        f"{context_text}"
    )


def _generate_invoice(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    context_text = require_str(args, "context")
    try:
        payload = ctx.llm_client.generate_json(_invoice_prompt(context_text), provider="codex")
        invoice = validate_invoice_data(payload)
    except (RoutingError, ValueError) as exc:
        try:
            retry = ctx.llm_client.generate_json(
                _invoice_prompt(context_text, validation_error=str(exc)), provider="codex"
            )
            invoice = validate_invoice_data(retry)
        except (RoutingError, ValueError) as retry_exc:
            return ToolResult(observation=f"ERROR: invoice generation failed twice: {retry_exc}")
    summary = (
        f"Invoice JSON generated and validated: invoice_no={invoice.get('invoice_no')}, "
        f"total={invoice.get('total')}, items={len(invoice.get('items', []))}. "
        "Stored for build_docx — call build_docx next to render it."
    )
    return ToolResult(observation=summary, structured=invoice)


def _build_docx(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    invoice = ctx.state.last_structured_result
    if not isinstance(invoice, dict):
        return ToolResult(observation="ERROR: build_docx requires a prior generate_invoice step in this run.")
    asset_id = ctx.state.selected_asset
    if not asset_id:
        return ToolResult(
            observation="ERROR: no active asset. Call read_memory (or create_asset) first so artifacts have a home."
        )
    source_files: list[str] = []
    for turn in ctx.state.turns:
        if turn.tool == "read_memory" and isinstance(turn.args.get("files"), list):
            source_files.extend(str(name) for name in turn.args["files"])
    artifact = build_invoice_docx_artifact(
        invoice,
        asset_id,
        ctx.file_writer,
        source_files=sorted(set(source_files)),
    )
    return ToolResult(
        observation=f"DOCX artifact written to {artifact.path}",
        artifact=artifact,
    )


ARTIFACT_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="generate_invoice",
        description="Generate validated, structured invoice JSON from supplied context text. Run after gathering memory/research. Result is held for build_docx.",
        args={"context": "all relevant facts for the invoice (memory excerpts, amounts, parties, dates)"},
        run=_generate_invoice,
    ),
    ToolSpec(
        name="build_docx",
        description="Render the most recent generate_invoice result into a DOCX artifact saved under the active asset's Artifact/ folder.",
        args={},
        run=_build_docx,
    ),
]
