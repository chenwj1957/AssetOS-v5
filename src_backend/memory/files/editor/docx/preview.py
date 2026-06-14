from __future__ import annotations

import html
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph


def docx_to_html(path: Path) -> str:
    """Render a .docx file's body as simple HTML for in-app preview.

    Walks paragraphs and tables in document order, mapping heading/title
    styles to ``<h1>``-``<h6>``, list styles to ``<ul><li>``, and tables to
    ``<table>``. This mirrors the front-end markdown renderer closely enough
    that artifact previews fit the same ``markdown-body`` styling.
    """
    document = Document(str(path))
    blocks: list[tuple[str, str]] = []

    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            block = _render_paragraph(Paragraph(child, document))
            if block:
                blocks.append(block)
        elif child.tag.endswith("}tbl"):
            rendered = _render_table(Table(child, document))
            if rendered:
                blocks.append(("block", rendered))

    parts: list[str] = []
    i = 0
    while i < len(blocks):
        kind, fragment = blocks[i]
        if kind == "list":
            items = []
            while i < len(blocks) and blocks[i][0] == "list":
                items.append(blocks[i][1])
                i += 1
            parts.append("<ul>" + "".join(items) + "</ul>")
        else:
            parts.append(fragment)
            i += 1
    return "\n".join(parts)


def _render_paragraph(paragraph: Paragraph) -> tuple[str, str] | None:
    text = paragraph.text.strip()
    if not text:
        return None
    style = (paragraph.style.name or "").lower()
    escaped = html.escape(text)
    if style.startswith("heading"):
        digits = "".join(ch for ch in style if ch.isdigit()) or "1"
        level = min(max(int(digits), 1), 6)
        return ("block", f"<h{level}>{escaped}</h{level}>")
    if style == "title":
        return ("block", f"<h1>{escaped}</h1>")
    if style.startswith("list"):
        return ("list", f"<li>{escaped}</li>")
    return ("block", f"<p>{escaped}</p>")


def _render_table(table: Table) -> str:
    rows_html = []
    for row_index, row in enumerate(table.rows):
        cell_tag = "th" if row_index == 0 else "td"
        cells = "".join(f"<{cell_tag}>{_render_cell_text(cell.text)}</{cell_tag}>" for cell in row.cells)
        rows_html.append(f"<tr>{cells}</tr>")
    if not rows_html:
        return ""
    return f"<table>{''.join(rows_html)}</table>"


def _render_cell_text(text: str) -> str:
    lines = [line.strip() for line in text.strip().splitlines()]
    return "<br>".join(html.escape(line) for line in lines if line)
