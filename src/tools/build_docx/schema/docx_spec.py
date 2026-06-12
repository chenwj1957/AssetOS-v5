from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.tools.build_docx.schema.blocks import DocumentBlock, block_from_dict, block_to_dict
from src.tools.build_docx.schema.page import PageSettings
from src.tools.build_docx.schema.styles import TextStyle


@dataclass(frozen=True)
class DocxSpec:
    metadata: dict[str, Any] = field(default_factory=dict)
    page: PageSettings = field(default_factory=PageSettings)
    styles: dict[str, TextStyle] = field(default_factory=dict)
    blocks: list[DocumentBlock] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DocxSpec:
        return cls(
            metadata=dict(payload.get("metadata", {})),
            page=PageSettings.from_dict(payload.get("page")),
            styles={
                name: TextStyle.from_dict(style)
                for name, style in dict(payload.get("styles", {})).items()
            },
            blocks=[block_from_dict(block) for block in payload.get("blocks", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": self.metadata,
            "page": self.page.to_dict(),
            "styles": {name: style.to_dict() for name, style in self.styles.items()},
            "blocks": [block_to_dict(block) for block in self.blocks],
        }
