"""Colored guidance evidence comparison; color/count remain unknown if unreadable."""
from .common import compare_basic


def compare(expected: dict, observed: dict) -> dict:
    return compare_basic(expected, observed, "colored_guidance")
