"""Canonical directive-line grammar shared by all preprocessor families.

Every repolish directive family (tags, keep, regex, multiregex) is recognized
by exactly one compiled pattern defined here. Extraction (``core``) and
application (``keep``/``regex``/``multiregex``) consume the same constants so
the two can never drift apart.

All patterns are compiled with ``re.MULTILINE`` so they serve both full-content
``findall`` (extraction) and per-line ``match`` on newline-stripped lines
(application); the flag does not change what a single stripped line matches.
"""

import re

# Region markers: ``repolish-start[name]`` ... ``repolish-end[name]``.
# Not a single-line directive — matches whole blocks, so it is only used by
# extraction; replacement builds per-tag patterns dynamically in ``anchors``.
TAG_BLOCK_RE = re.compile(
    # allow empty inner block (no extra blank line required before end)
    r'^[^\n]*repolish-start\[(.+?)\][^\n]*\n(.*?)[^\n]*repolish-end\[\1\][^\n]*',
    re.DOTALL | re.MULTILINE,
)

# ``repolish-regex[name]: <pattern>``
REGEX_DIRECTIVE_RE = re.compile(
    r'^[^\n]*repolish-regex\[(.+?)\]:\s*(.*?)\s*$',
    re.MULTILINE,
)

# ``repolish-keep-block[name]: start="..." end="..."`` (or end-regex="...")
# Capturing groups are name, start marker, end mode, end value, in that order.
KEEP_BLOCK_DIRECTIVE_RE = re.compile(
    r'^[^\n]*repolish-keep-block\[(.+?)\]:\s*start=("(?:\\.|[^"])*")\s+(end|end-regex)=("(?:\\.|[^"])*")\s*$',
    re.MULTILINE,
)

# ``repolish-keep-rest[name]: marker="..."`` (aliases: the-rest, footer)
KEEP_REST_DIRECTIVE_RE = re.compile(
    r'^[^\n]*repolish-keep-(?:rest|the-rest|footer)\[(.+?)\]:\s*marker=("(?:\\.|[^"])*")\s*$',
    re.MULTILINE,
)

# ``repolish-keep-header[name]: marker="..."`` (alias: the-header)
KEEP_HEADER_DIRECTIVE_RE = re.compile(
    r'^[^\n]*repolish-keep-(?:header|the-header)\[(.+?)\]:\s*marker=("(?:\\.|[^"])*")\s*$',
    re.MULTILINE,
)

# ``repolish-multiregex-block[name]: <pattern>``
MULTIREGEX_BLOCK_DIRECTIVE_RE = re.compile(
    r'^[^\n]*repolish-multiregex-block\[(.+?)\]:\s*(.*?)\s*$',
    re.MULTILINE,
)

# ``repolish-multiregex[name]: <pattern>``
MULTIREGEX_DIRECTIVE_RE = re.compile(
    r'^[^\n]*repolish-multiregex\[(.+?)\]:\s*(.*?)\s*$',
    re.MULTILINE,
)
