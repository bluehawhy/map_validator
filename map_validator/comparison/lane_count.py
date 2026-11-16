"""Lane counts: compare only recognized integer values."""
from .common import compare_basic


def compare(expected: dict, observed: dict, field: str) -> dict:
    return compare_basic(expected, observed, field)
