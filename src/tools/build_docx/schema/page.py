from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class PageSettings:
    size: str = "A4"
    orientation: str = "portrait"
    margins: dict[str, float] = field(
        default_factory=lambda: {"top": 0.6, "bottom": 0.6, "left": 0.7, "right": 0.7}
    )

    @classmethod
    def from_dict(cls, payload: dict | None) -> PageSettings:
        payload = payload or {}
        return cls(
            size=str(payload.get("size", "A4")),
            orientation=str(payload.get("orientation", "portrait")),
            margins={**cls().margins, **dict(payload.get("margins", {}))},
        )

    def to_dict(self) -> dict:
        return asdict(self)
