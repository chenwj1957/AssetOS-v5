from __future__ import annotations

from typing import Any

from src.tools.build_docx.schema import (
    DocxSpec,
    KeyValueTableBlock,
    PageSettings,
    ParagraphBlock,
    SpacerBlock,
    TableBlock,
    TextStyle,
)


def classic_tax_invoice(invoice: dict[str, Any]) -> DocxSpec:
    business_profile = _dict_value(invoice, "business_profile")
    payment = _dict_value(business_profile, "payment")
    contact = _dict_value(business_profile, "contact")
    business_name = _text(business_profile.get("business_name") or business_profile.get("trading_name"))
    trading_name = _text(business_profile.get("trading_name") or business_name)
    abn = _text(business_profile.get("abn"))
    reference = _text(invoice.get("invoice_no"))
    total = _amount(invoice.get("total"))

    return DocxSpec(
        metadata={"document_type": "invoice", "layout": "classic_tax_invoice"},
        page=PageSettings(size="A4", orientation="portrait"),
        styles={
            "normal": TextStyle(font_name="Arial", font_size=9),
            "title": TextStyle(font_name="Arial", font_size=18, bold=True, alignment="right"),
            "section": TextStyle(font_name="Arial", font_size=10, bold=True),
            "small": TextStyle(font_name="Arial", font_size=8),
            "table_header": TextStyle(font_name="Arial", font_size=8, bold=True),
            "total": TextStyle(font_name="Arial", font_size=10, bold=True, alignment="right"),
        },
        blocks=[
            TableBlock(
                columns=2,
                border="none",
                column_widths=[58, 42],
                rows=[
                    [
                        [
                            ParagraphBlock(text=business_name, style="section"),
                            ParagraphBlock(text=trading_name, style="small"),
                            ParagraphBlock(text=_text(contact.get("email")), style="small"),
                            ParagraphBlock(text=_text(contact.get("phone")), style="small"),
                        ],
                        [
                            ParagraphBlock(text="TAX INVOICE", style="title", alignment="right"),
                            KeyValueTableBlock(
                                rows=[
                                    ["ABN", abn],
                                    ["Date", _text(invoice.get("invoice_date"))],
                                    ["Customer No", _text(invoice.get("customer_no"))],
                                    ["Page", "1 of 1"],
                                ],
                                column_widths=[35, 65],
                            ),
                        ],
                    ]
                ],
            ),
            SpacerBlock(height=8),
            KeyValueTableBlock(
                rows=[
                    ["Bill To", _text(invoice.get("bill_to"))],
                    ["Property", _text(invoice.get("property_name"))],
                    ["Address", _text(invoice.get("property_address"))],
                    ["Billing Period", _text(invoice.get("billing_period"))],
                    ["Due Date", _text(invoice.get("due_date"))],
                ],
                column_widths=[28, 72],
            ),
            SpacerBlock(height=8),
            _invoice_items_table(invoice),
            SpacerBlock(height=8),
            TableBlock(
                columns=2,
                border="single",
                column_widths=[72, 28],
                rows=[
                    ["TOTAL NET", _amount(invoice.get("subtotal"))],
                    ["GST", _amount(invoice.get("gst"))],
                    ["TOTAL Inc. GST", total],
                ],
            ),
            SpacerBlock(height=8),
            ParagraphBlock(text=f"Payment reference: {reference}", style="section"),
            KeyValueTableBlock(
                rows=[
                    ["Payment Method", "Direct Credit"],
                    ["Account Name", _text(payment.get("account_name"))],
                    ["BSB", _text(payment.get("bsb"))],
                    ["Account Number", _text(payment.get("account_number"))],
                    ["Reference", reference],
                ],
                column_widths=[28, 72],
            ),
            # SpacerBlock(height=8),
            # TableBlock(
            #     columns=2,
            #     border="single",
            #     column_widths=[50, 50],
            #     rows=[
            #         [
            #             [
            #                 ParagraphBlock(text="Remittance", style="section"),
            #                 ParagraphBlock(text=f"Invoice Date: {_text(invoice.get('invoice_date'))}"),
            #                 ParagraphBlock(text=f"Account: {_text(invoice.get('account'))}"),
            #             ],
            #             [
            #                 ParagraphBlock(text=f"Invoice: {reference}"),
            #                 ParagraphBlock(text=f"Amount: {total}", style="total", alignment="right"),
            #             ],
            #         ]
            #     ],
            # ),
        ],
    )


def _invoice_items_table(invoice: dict[str, Any]) -> TableBlock:
    rows = [[_text(item.get("description")), _amount(item.get("amount"))] for item in invoice.get("items", [])]
    return TableBlock(
        columns=2,
        headers=["DESCRIPTION", "VALUE"],
        rows=rows,
        border="single",
        column_widths=[72, 28],
    )


def _dict_value(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "To be confirmed"


def _amount(value: Any) -> str:
    if isinstance(value, int | float):
        return f"${value:,.2f}"
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "To be confirmed"
