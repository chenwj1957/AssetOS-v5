from __future__ import annotations

from typing import TYPE_CHECKING

from docx.enum.section import WD_ORIENTATION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from src.tools.build_docx.schema.blocks import DocumentBlock

if TYPE_CHECKING:
    from docx.document import Document
    from docx.table import _Cell, Table
    from docx.text.paragraph import Paragraph

    from src.tools.build_docx.builder import DocxBuilder
    from src.tools.build_docx.schema.styles import TextStyle


ALIGNMENTS = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}


def apply_page_settings(document: Document, size: str, orientation: str, margins: dict[str, float]) -> None:
    section = document.sections[0]
    if orientation == "landscape":
        section.orientation = WD_ORIENTATION.LANDSCAPE
        section.page_width, section.page_height = section.page_height, section.page_width
    section.top_margin = Inches(float(margins.get("top", 0.6)))
    section.bottom_margin = Inches(float(margins.get("bottom", 0.6)))
    section.left_margin = Inches(float(margins.get("left", 0.7)))
    section.right_margin = Inches(float(margins.get("right", 0.7)))


def set_paragraph_alignment(paragraph: Paragraph, alignment: str | None) -> None:
    if alignment in ALIGNMENTS:
        paragraph.alignment = ALIGNMENTS[alignment]


def apply_paragraph_spacing(paragraph: Paragraph) -> None:
    paragraph.paragraph_format.space_before = Pt(6)
    paragraph.paragraph_format.space_after = Pt(6)


def apply_text_style(run, style: TextStyle | None) -> None:
    if style is None:
        return
    run.font.name = style.font_name
    run.font.size = Pt(style.font_size)
    run.bold = style.bold
    run.italic = style.italic
    run.underline = style.underline
    if style.color:
        run.font.color.rgb = RGBColor.from_string(style.color.lstrip("#"))


def set_cell_text(cell: _Cell, value: object, style: TextStyle | None = None, alignment: str | None = None) -> None:
    clear_cell(cell)
    paragraph = cell.paragraphs[0]
    apply_paragraph_spacing(paragraph)
    set_paragraph_alignment(paragraph, alignment or (style.alignment if style else None))
    run = paragraph.add_run(str(value))
    apply_text_style(run, style)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def set_cell_blocks(cell: _Cell, blocks: list[DocumentBlock], builder: DocxBuilder) -> None:
    clear_cell(cell)
    render_nested_blocks(cell, blocks, builder)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def clear_cell(cell: _Cell) -> None:
    cell.text = ""


def render_nested_blocks(cell: _Cell, blocks: list[DocumentBlock], builder: DocxBuilder) -> None:
    for block in blocks:
        builder.render_block(block, container=cell)


def set_table_borders(table: Table, border: str = "single") -> None:
    if border == "none":
        return
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = f"w:{edge}"
        element = borders.find(qn(tag))
        if element is None:
            element = OxmlElement(tag)
            borders.append(element)
        element.set(qn("w:val"), border)
        element.set(qn("w:sz"), "4")
        element.set(qn("w:space"), "0")
        element.set(qn("w:color"), "BFBFBF")


def set_column_widths(table: Table, widths: list[float]) -> None:
    if not widths:
        return
    total = sum(widths)
    if total <= 0:
        return
    table_width_inches = 7.0
    for row in table.rows:
        for index, width in enumerate(widths[: len(row.cells)]):
            row.cells[index].width = Inches(table_width_inches * (width / total))


def add_horizontal_rule(paragraph: Paragraph) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    border = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "808080")
    border.append(bottom)
    p_pr.append(border)


def align_table(table: Table) -> None:
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
