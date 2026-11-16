"""Dispatch comparison by feature, never by clock position or fixed direction."""
from __future__ import annotations

from . import colored_guidance, guidance_line, lane_arrows, lane_count, road_presence, stop_line


def compare_values(expected: dict, observed: dict, field: str) -> dict:
    if field == "stop_line":
        return stop_line.compare(expected, observed)
    if field == "road_exists":
        return road_presence.compare(expected, observed)
    if field in ("entry_lane_count", "exit_lane_count"):
        return lane_count.compare(expected, observed, field)
    if field == "lane_arrows":
        return lane_arrows.compare(expected, observed)
    if field == "guidance_line":
        return guidance_line.compare(expected, observed)
    if field == "colored_guidance":
        return colored_guidance.compare(expected, observed)
    raise ValueError(f"정의되지 않은 비교 항목: {field}")
