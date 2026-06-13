from __future__ import annotations

from pathlib import Path

from src.core.errors import UnsafeMemoryPathError


def resolve_within(root: Path, relative: str, *, label: str) -> Path:
    """Resolve ``relative`` under ``root``, rejecting any path that escapes it.

    Shared by asset/file/fact path handling so the same traversal rules
    (no absolute paths, no ``..`` segments, no symlink escapes) apply
    everywhere a caller-supplied relative path touches memory on disk.
    """
    candidate = Path(relative)
    if candidate.is_absolute():
        raise UnsafeMemoryPathError(f"{label} must be a relative path: {relative}")
    if ".." in candidate.parts:
        raise UnsafeMemoryPathError(f"{label} cannot contain parent-directory references: {relative}")

    root_resolved = root.resolve()
    resolved = (root_resolved / candidate).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise UnsafeMemoryPathError(f"{label} escapes its root directory: {relative}") from exc
    return resolved
