"""Read-only discovery of immutable individual input-tool capture PNGs.

The filesystem is the source of truth for which raw capture revisions exist.
A missing or stale manifest must not hide an existing original photograph.
"""
from __future__ import annotations

import re
from pathlib import Path

_ORIGINAL = re.compile(r"input_tool_r([0-9]{3,})\.png\Z")


def list_individual_capture_files(folder: Path) -> dict[int, Path]:
    """Find raw rNNN PNGs only, excluding overlays, focus and symlinks."""
    root = folder / "captures"
    directory = root / "individual"
    if root.is_symlink() or directory.is_symlink() or not directory.is_dir():
        return {}

    captures: dict[int, Path] = {}
    for path in directory.iterdir():
        if not path.is_file() or path.is_symlink():
            continue
        match = _ORIGINAL.fullmatch(path.name)
        if match is None:
            continue
        revision = int(match.group(1))
        # Reject alternate spellings (e.g. r0001) of an existing revision.
        if revision < 1 or path.name != f"input_tool_r{revision:03d}.png":
            continue
        captures[revision] = path
    return dict(sorted(captures.items()))
