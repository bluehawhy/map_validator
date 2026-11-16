"""Ordinary guidance-line evidence comparison (separate from colored lines)."""
from .common import compare_basic


def compare(expected: dict, observed: dict) -> dict:
    return compare_basic(expected, observed, "guidance_line")
