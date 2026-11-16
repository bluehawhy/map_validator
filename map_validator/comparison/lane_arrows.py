"""Per-lane arrows, including combinations, pending verified recognition."""
from .common import compare_basic


def compare(expected: dict, observed: dict) -> dict:
    return compare_basic(expected, observed, "lane_arrows")
