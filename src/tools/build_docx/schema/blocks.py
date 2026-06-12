from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


CellValue = str | int | float | list["DocumentBlock"]


@dataclass(frozen=True)
class ParagraphBlock:
    type: Literal["paragraph"] = "paragraph"
    text: str = ""
    style: str | None = None
    alignment: str | None = None


@dataclass(frozen=True)
class TableBlock:
    type: Literal["table"] = "table"
    columns: int = 1
    headers: list[CellValue] = field(default_factory=list)
    rows: list[list[CellValue]] = field(default_factory=list)
    border: str = "single"
    column_widths: list[float] = field(default_factory=list)
    width: str = "100%"


@dataclass(frozen=True)
class KeyValueTableBlock:
    type: Literal["key_value_table"] = "key_value_table"
    rows: list[list[CellValue]] = field(default_factory=list)
    border: str = "single"
    column_widths: list[float] = field(default_factory=lambda: [35, 65])


@dataclass(frozen=True)
class SpacerBlock:
    type: Literal["spacer"] = "spacer"
    height: int = 12


@dataclass(frozen=True)
class HorizontalRuleBlock:
    type: Literal["horizontal_rule"] = "horizontal_rule"


@dataclass(frozen=True)
class PageBreakBlock:
    type: Literal["page_break"] = "page_break"


DocumentBlock = ParagraphBlock | TableBlock | KeyValueTableBlock | SpacerBlock | HorizontalRuleBlock | PageBreakBlock


def block_from_dict(payload: dict[str, Any]) -> DocumentBlock:
    block_type = payload.get("type")
    if block_type == "paragraph":
        return ParagraphBlock(
            text=str(payload.get("text", "")),
            style=payload.get("style"),
            alignment=payload.get("alignment"),
        )
    if block_type == "table":
        return TableBlock(
            columns=int(payload.get("columns", 1)),
            headers=[_parse_cell(cell) for cell in payload.get("headers", [])],
            rows=[[_parse_cell(cell) for cell in row] for row in payload.get("rows", [])],
            border=str(payload.get("border", "single")),
            column_widths=[float(width) for width in payload.get("column_widths", [])],
            width=str(payload.get("width", "100%")),
        )
    if block_type == "key_value_table":
        return KeyValueTableBlock(
            rows=[[_parse_cell(cell) for cell in row] for row in payload.get("rows", [])],
            border=str(payload.get("border", "single")),
            column_widths=[float(width) for width in payload.get("column_widths", [35, 65])],
        )
    if block_type == "spacer":
        return SpacerBlock(height=int(payload.get("height", 12)))
    if block_type == "horizontal_rule":
        return HorizontalRuleBlock()
    if block_type == "page_break":
        return PageBreakBlock()
    raise ValueError(f"Unsupported DOCX block type: {block_type}")


def block_to_dict(block: DocumentBlock) -> dict[str, Any]:
    payload = asdict(block)
    if isinstance(block, (TableBlock, KeyValueTableBlock)):
        payload["rows"] = [[_cell_to_dict(cell) for cell in row] for row in block.rows]
        if isinstance(block, TableBlock):
            payload["headers"] = [_cell_to_dict(cell) for cell in block.headers]
    return payload


def _parse_cell(value: Any) -> CellValue:
    if isinstance(value, list):
        return [block_from_dict(block) for block in value]
    if isinstance(value, int | float):
        return value
    return str(value)


def _cell_to_dict(value: CellValue) -> Any:
    if isinstance(value, list):
        return [block_to_dict(block) for block in value]
    return value
