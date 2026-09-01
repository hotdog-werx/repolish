"""Shared tag-name parsing helpers for directive families."""

from __future__ import annotations

import re

_TAG_NAME_CHARS = r'A-Za-z0-9_-'
_TAG_NAME_RE = re.compile(rf'^[{_TAG_NAME_CHARS}]+$')
_SECTION_HEADER_RE = re.compile(rf'^\[([{_TAG_NAME_CHARS}]+)\]$')


def is_valid_tag_name(name: str) -> bool:
    """Return True when *name* uses supported tag characters."""
    return bool(_TAG_NAME_RE.fullmatch(name))


def parse_section_name(line: str) -> str | None:
    """Return section name from a header line like ``[name]`` or None."""
    match = _SECTION_HEADER_RE.fullmatch(line.strip())
    if not match:
        return None
    return match.group(1)
