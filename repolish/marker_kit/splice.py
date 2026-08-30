"""Offset-safe span replacement for marker-driven rewrites."""

from collections.abc import Iterable


def apply_splices(
    text: str,
    splices: Iterable[tuple[int, int, str]],
) -> str:
    """Apply ``(start, end, replacement)`` splices to *text*.

    Splices are char-offset half-open spans into the original *text*; overlaps
    are the caller's responsibility. Replacements are applied right-to-left so
    earlier offsets stay valid regardless of replacement lengths.
    """
    result = text
    for start, end, replacement in sorted(
        splices,
        key=lambda splice: splice[0],
        reverse=True,
    ):
        result = result[:start] + replacement + result[end:]
    return result
