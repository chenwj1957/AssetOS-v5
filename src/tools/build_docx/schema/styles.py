from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class TextStyle:
    font_name: str = "Arial"
    font_size: int = 10
    bold: bool = False
    italic: bool = False
    underline: bool = False
    color: str | None = None
    alignment: str | None = None

    @classmethod
    def from_dict(cls, payload: dict) -> TextStyle:
        return cls(
            font_name=str(payload.get("font_name", "Arial")),
            font_size=int(payload.get("font_size", 10)),
            bold=bool(payload.get("bold", False)),
            italic=bool(payload.get("italic", False)),
            underline=bool(payload.get("underline", False)),
            color=payload.get("color"),
            alignment=payload.get("alignment"),
        )

    def to_dict(self) -> dict:
        return asdict(self)
