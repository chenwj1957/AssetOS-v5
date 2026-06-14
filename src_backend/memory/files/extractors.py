from __future__ import annotations

import csv
from pathlib import Path

# Cap rows per sheet/table so huge workbooks don't produce unbounded Markdown;
# read_file truncates anyway, but this keeps extraction itself fast.
MAX_EXTRACT_ROWS = 500


def extract_to_markdown(path: Path) -> tuple[str, str] | None:
    """Deterministically convert a structured office file to Markdown plus a
    short summary, without an LLM call. Returns ``None`` for formats that
    need an LLM (e.g. images, scanned PDFs) so callers can fall back."""
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm", ".xls"):
        return _extract_spreadsheet(path)
    if suffix == ".csv":
        return _extract_csv(path)
    if suffix == ".docx":
        return _extract_docx(path)
    return None


def _row_to_markdown(row: list[str]) -> str:
    return "| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |"


def _table_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return "_(empty)_"
    header, body = rows[0], rows[1:]
    lines = [_row_to_markdown(header), _row_to_markdown(["---"] * len(header))]
    lines.extend(_row_to_markdown(row) for row in body)
    if len(body) >= MAX_EXTRACT_ROWS:
        lines.append(f"\n_(truncated to {MAX_EXTRACT_ROWS} rows)_")
    return "\n".join(lines)


def _cell_text(value: object) -> str:
    return "" if value is None else str(value)


def _extract_spreadsheet(path: Path) -> tuple[str, str]:
    import openpyxl

    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    sections = []
    for sheet in workbook.worksheets:
        rows = []
        for row in sheet.iter_rows(max_row=MAX_EXTRACT_ROWS + 1, values_only=True):
            if all(cell is None for cell in row):
                continue
            rows.append([_cell_text(cell) for cell in row])
        sections.append(f"## Sheet: {sheet.title}\n\n{_table_to_markdown(rows)}")
    workbook.close()
    markdown = f"# {path.name}\n\n" + "\n\n".join(sections)
    sheet_names = ", ".join(sheet.title for sheet in workbook.worksheets)
    summary = f"Spreadsheet '{path.name}' with sheets: {sheet_names}."
    return markdown, summary


def _extract_csv(path: Path) -> tuple[str, str]:
    with path.open(newline="", encoding="utf-8", errors="ignore") as handle:
        rows = [row for row in csv.reader(handle)][: MAX_EXTRACT_ROWS + 1]
    markdown = f"# {path.name}\n\n{_table_to_markdown(rows)}"
    summary = f"CSV file '{path.name}' with {max(len(rows) - 1, 0)} data rows."
    return markdown, summary


def _extract_docx(path: Path) -> tuple[str, str]:
    from docx import Document

    document = Document(path)
    parts = [f"# {path.name}\n"]
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text:
            parts.append(text)
    for table_index, table in enumerate(document.tables, start=1):
        rows = [[cell.text.strip() for cell in row.cells] for row in table.rows[: MAX_EXTRACT_ROWS + 1]]
        parts.append(f"\n## Table {table_index}\n\n{_table_to_markdown(rows)}")
    markdown = "\n\n".join(parts)
    summary = f"Word document '{path.name}' with {len(document.paragraphs)} paragraphs and {len(document.tables)} table(s)."
    return markdown, summary
