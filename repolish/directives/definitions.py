"""Canonical directive-line grammar shared by all directive families.

Every repolish directive family (tags, keep, regex, multiregex) is recognized
by exactly one compiled pattern defined here. Extraction (``core``) and
application (``keep``/``regex``/``multiregex``) consume the same constants so
the two can never drift apart.

All patterns are compiled with ``re.MULTILINE`` so they serve both full-content
``findall`` (extraction) and per-line ``match`` on newline-stripped lines
(application); the flag does not change what a single stripped line matches.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from hotlog import get_logger

from repolish.directives.phases import split_directive_tag

logger = get_logger(__name__)

T = TypeVar('T')

# Namespace separator: ``repolish:<command>`` is the current grammar form;
# the legacy ``repolish-<command>`` dash form is still accepted but deprecated
# (see ``warn_legacy_dash_directives``; dash form removal planned for v2).
# The post-tag colon is optional: ``repolish:regex[n] <payload>`` and the legacy
# ``repolish-regex[n]: <payload>`` both match. Payload payloads are
# whitespace-separated after ``[tag]``.

# Region markers: ``repolish:start[name]`` ... ``repolish:end[name]``.
# Not a single-line directive — matches whole blocks, so it is only used by
# extraction; replacement builds per-tag patterns dynamically in ``anchors``.
TAG_BLOCK_RE = re.compile(
    # allow empty inner block (no extra blank line required before end)
    r'^[^\n]*repolish[-:]start\[(.+?)\][^\n]*\n(.*?)[^\n]*repolish[-:]end\[\1\][^\n]*',
    re.DOTALL | re.MULTILINE,
)

# ``repolish:regex[name] <pattern>``
REGEX_DIRECTIVE_RE = re.compile(
    r'^[^\n]*repolish[-:]regex\[(.+?)\]:?\s*(.*?)\s*$',
    re.MULTILINE,
)

# ``repolish:keep-block[name] start="..." end="..."`` (or end-regex="...")
# Capturing groups are name, start marker, end mode, end value, in that order.
KEEP_BLOCK_DIRECTIVE_RE = re.compile(
    r'^[^\n]*repolish[-:]keep-block\[(.+?)\]:?\s*start=("(?:\\.|[^"])*")\s+(end|end-regex)=("(?:\\.|[^"])*")\s*$',
    re.MULTILINE,
)

# ``repolish:keep-rest[name] marker="..."`` (aliases: the-rest, footer)
KEEP_REST_DIRECTIVE_RE = re.compile(
    r'^[^\n]*repolish[-:]keep-(?:rest|the-rest|footer)\[(.+?)\]:?\s*marker=("(?:\\.|[^"])*")\s*$',
    re.MULTILINE,
)

# ``repolish:keep-header[name] marker="..."`` (alias: the-header)
KEEP_HEADER_DIRECTIVE_RE = re.compile(
    r'^[^\n]*repolish[-:]keep-(?:header|the-header)\[(.+?)\]:?\s*marker=("(?:\\.|[^"])*")\s*$',
    re.MULTILINE,
)

# ``repolish:multiregex-block[name] <pattern>``
MULTIREGEX_BLOCK_DIRECTIVE_RE = re.compile(
    r'^[^\n]*repolish[-:]multiregex-block\[(.+?)\]:?\s*(.*?)\s*$',
    re.MULTILINE,
)

# ``repolish:multiregex[name] <pattern>``
MULTIREGEX_DIRECTIVE_RE = re.compile(
    r'^[^\n]*repolish[-:]multiregex\[(.+?)\]:?\s*(.*?)\s*$',
    re.MULTILINE,
)

# Deprecated dash-namespace detection: ``repolish-<command>[`` for any known
# directive command. Insertions (``repolish:on``/``repolish:off``) never had a
# dash spelling, so they are not here.
LEGACY_DASH_DIRECTIVE_RE = re.compile(
    r'^[^\n]*repolish-(?:multiregex-block|multiregex|keep-the-rest|keep-the-header'
    r'|keep-block|keep-rest|keep-footer|keep-header|regex|start|end)\[',
    re.MULTILINE,
)


def warn_legacy_dash_directives(
    content: str,
    *,
    source_path: str | None = None,
) -> None:
    """Warn once when *content* uses the deprecated ``repolish-*`` grammar.

    Called from extraction (pre-render pass only, so each file warns a single
    time even though extraction runs once per phase).
    """
    matches = LEGACY_DASH_DIRECTIVE_RE.findall(content)
    if not matches:
        return
    logger.warning(
        'legacy_directive_namespace',
        count=len(matches),
        new_form='repolish:<command>[tag] <payload>',
        removal='v2',
        source_path=source_path,
    )


@dataclass(frozen=True)
class DirectiveMapDefinition(Generic[T]):
    """How to turn one family's directive-line matches into extracted values.

    ``parse_value`` receives the pattern's captured groups after the bracketed
    name, in order, and returns the payload stored for that directive.
    """

    pattern: re.Pattern[str]
    parse_value: Callable[..., T]


def extract_directive_map(
    content: str,
    definition: DirectiveMapDefinition[T],
    *,
    phase: str,
    source_path: str | None = None,
) -> dict[str, T]:
    """Extract a phase-filtered directive map keyed by logical directive name."""
    result: dict[str, T] = {}
    for match in definition.pattern.findall(content):
        raw_name, *values = match
        name, directive_phase = split_directive_tag(
            raw_name,
            source_path=source_path,
        )
        if directive_phase != phase:
            continue
        result[name] = definition.parse_value(*values)
    return result
