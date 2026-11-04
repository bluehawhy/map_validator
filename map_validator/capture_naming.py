"""Consistent, Windows-safe evidence filenames for both captured programs."""
from __future__ import annotations

import re


def capture_file_name(case_id: str, program_title: str, frame_index: int, frame_count: int) -> str:
    """Generate <case ID>_<program>.png, adding an index only for multi-frame runs."""
    case_name = re.sub(r"\s*-\s*(?=Link\b)", "-", case_id.strip(), flags=re.IGNORECASE)
    program_name = program_title.strip()
    # Keep user-facing names intact except characters Windows cannot accept.
    def safe(value: str) -> str:
        return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).rstrip(" .")

    if not case_name or not program_name:
        raise ValueError("검수 ID와 프로그램명이 있어야 캡처 파일명을 만들 수 있습니다.")

    suffix = f"_{frame_index + 1:02d}" if frame_count > 1 else ""
    return f"{safe(case_name)}_{safe(program_name)}{suffix}.png"
