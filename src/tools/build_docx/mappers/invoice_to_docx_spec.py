from __future__ import annotations

from typing import Any

from src.tools.build_docx.layouts.invoice import classic_tax_invoice
from src.tools.build_docx.schema.docx_spec import DocxSpec
from src.tools.build_docx.schema.invoice import validate_invoice_data


def invoice_to_docx_spec(
    invoice: dict[str, Any],
    layout: str = "classic_tax_invoice",
) -> DocxSpec:
    invoice_data = validate_invoice_data(invoice)
    if layout == "classic_tax_invoice":
        return classic_tax_invoice(invoice_data)
    raise ValueError(f"Unsupported invoice DOCX layout: {layout}")
