from __future__ import annotations


def truncate_text(text: str, limit: int, marker: str = "\n...[truncated]") -> str:
    """Truncate ``text`` to ``limit`` characters, appending ``marker`` if cut."""
    if len(text) <= limit:
        return text
    return text[:limit] + marker


def trim_to_budget(items: list[str], limit: int, marker: str, used: int = 0) -> list[str]:
    """Keep the newest items (from the end of ``items``) within a character budget.

    Iterates ``items`` newest-first, accumulating until adding another item
    would exceed ``limit``. If anything is dropped, ``marker`` is inserted in
    its place. Returns the kept items in their original order.
    """
    kept: list[str] = []
    for item in reversed(items):
        if used + len(item) > limit and kept:
            kept.append(marker)
            break
        kept.append(item)
        used += len(item)
    return list(reversed(kept))
