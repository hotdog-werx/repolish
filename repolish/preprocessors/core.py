"""Core preprocessing utilities for templates.

This module provides the main functions for extracting patterns from templates,
replacing tags, and orchestrating the complete text replacement pipeline.
"""

import ast
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from hotlog import get_logger

from repolish.preprocessors.anchors import replace_tags_in_content
from repolish.preprocessors.keep import (
    KeepBlockSpec,
    KeepMarkerSpec,
    KeepPatterns,
    apply_keep_replacements,
)
from repolish.preprocessors.multiregex import apply_multiregex_replacements
from repolish.preprocessors.regex import apply_regex_replacements
from repolish.utils import read_text_utf8

logger = get_logger(__name__)

T = TypeVar('T')


@dataclass
class Patterns:
    """Container for extracted patterns from content."""

    tag_blocks: dict[str, str]
    keep_blocks: dict[str, tuple[str, str]]
    keep_rest: dict[str, str]
    keep_header: dict[str, str]
    regexes: dict[str, str]
    multiregex_blocks: dict[str, str]
    multiregexes: dict[str, str]


@dataclass(frozen=True)
class _PatternDefinition(Generic[T]):
    """Definition for a phase-aware directive map extracted from content."""

    pattern: re.Pattern[str]
    parse_value: Callable[..., T]


_TAG_PATTERN = re.compile(
    # allow empty inner block (no extra blank line required before end)
    r'^[^\n]*repolish-start\[(.+?)\][^\n]*\n(.*?)[^\n]*repolish-end\[\1\][^\n]*',
    re.DOTALL | re.MULTILINE,
)

_REGEX_PATTERN_DEF = _PatternDefinition[str](
    pattern=re.compile(
        r'^[^\n]*repolish-regex\[(.+?)\]:\s*(.*?)\s*$',
        re.MULTILINE,
    ),
    parse_value=lambda pattern: pattern,
)

_KEEP_BLOCK_PATTERN_DEF = _PatternDefinition[tuple[str, str]](
    pattern=re.compile(
        r'^[^\n]*repolish-keep-block\[(.+?)\]:\s*start=("(?:\\.|[^"])*")\s+end=("(?:\\.|[^"])*")\s*$',
        re.MULTILINE,
    ),
    parse_value=lambda start_raw, end_raw: (
        _parse_keep_literal(start_raw),
        _parse_keep_literal(end_raw),
    ),
)

_KEEP_REST_PATTERN_DEF = _PatternDefinition[str](
    pattern=re.compile(
        r'^[^\n]*repolish-keep-(?:rest|the-rest|footer)\[(.+?)\]:\s*marker=("(?:\\.|[^"])*")\s*$',
        re.MULTILINE,
    ),
    parse_value=lambda marker_raw: _parse_keep_literal(marker_raw),
)

_KEEP_HEADER_PATTERN_DEF = _PatternDefinition[str](
    pattern=re.compile(
        r'^[^\n]*repolish-keep-(?:header|the-header)\[(.+?)\]:\s*marker=("(?:\\.|[^"])*")\s*$',
        re.MULTILINE,
    ),
    parse_value=lambda marker_raw: _parse_keep_literal(marker_raw),
)

_MULTIREGEX_BLOCK_PATTERN_DEF = _PatternDefinition[str](
    pattern=re.compile(
        r'^[^\n]*repolish-multiregex-block\[(.+?)\]:\s*(.*?)\s*$',
        re.MULTILINE,
    ),
    parse_value=lambda pattern: pattern,
)

_MULTIREGEX_PATTERN_DEF = _PatternDefinition[str](
    pattern=re.compile(
        r'^[^\n]*repolish-multiregex\[(.+?)\]:\s*(.*?)\s*$',
        re.MULTILINE,
    ),
    parse_value=lambda pattern: pattern,
)


def _split_directive_tag(raw_tag: str) -> tuple[str, str]:
    """Split directive tag into `(name, phase)` with `pre-render` default."""
    if '|' not in raw_tag:
        return raw_tag, 'pre-render'

    name, maybe_phase = raw_tag.rsplit('|', 1)
    if maybe_phase in {'pre-render', 'after-render'} and name:
        return name, maybe_phase
    return raw_tag, 'pre-render'


def _is_phase_selected(
    directive_phase: str,
    selected_phase: str = 'pre-render',
) -> bool:
    """Return True when a directive phase should run in selected phase."""
    return directive_phase == selected_phase


def _parse_keep_literal(raw: str) -> str:
    """Parse a quoted keep directive literal."""
    value = ast.literal_eval(raw)
    if not isinstance(value, str):
        msg = 'keep directive values must be quoted strings'
        raise TypeError(msg)
    return value


def _extract_tag_blocks(content: str) -> dict[str, str]:
    """Extract repolish-start/end blocks preserving only inner content."""
    raw_tag_blocks = dict(_TAG_PATTERN.findall(content))
    return {key: value.strip('\n') for key, value in raw_tag_blocks.items()}


def _extract_directive_map(
    content: str,
    definition: _PatternDefinition[T],
    *,
    phase: str,
) -> dict[str, T]:
    """Extract a phase-filtered directive map keyed by logical directive name."""
    result: dict[str, T] = {}
    for match in definition.pattern.findall(content):
        raw_name, *values = match
        name, directive_phase = _split_directive_tag(raw_name)
        if not _is_phase_selected(directive_phase, phase):
            continue
        result[name] = definition.parse_value(*values)
    return result


def extract_patterns(content: str, *, phase: str = 'pre-render') -> Patterns:
    """Extracts text blocks and regex patterns from the given content.

    Args:
        content: The input string containing text blocks and regex patterns.
        phase: Directive phase to extract (`pre-render` or `after-render`).

    Returns:
        A Patterns object containing extracted tag blocks and regexes.
    """
    tag_blocks = _extract_tag_blocks(content)
    keep_blocks = _extract_directive_map(
        content,
        _KEEP_BLOCK_PATTERN_DEF,
        phase=phase,
    )
    keep_rest = _extract_directive_map(
        content,
        _KEEP_REST_PATTERN_DEF,
        phase=phase,
    )
    keep_header = _extract_directive_map(
        content,
        _KEEP_HEADER_PATTERN_DEF,
        phase=phase,
    )
    regexes = _extract_directive_map(
        content,
        _REGEX_PATTERN_DEF,
        phase=phase,
    )
    multiregex_blocks = _extract_directive_map(
        content,
        _MULTIREGEX_BLOCK_PATTERN_DEF,
        phase=phase,
    )
    multiregexes = _extract_directive_map(
        content,
        _MULTIREGEX_PATTERN_DEF,
        phase=phase,
    )

    logger.debug(
        'extracted_patterns',
        tag_blocks=[str(k) for k in tag_blocks],
        keep_blocks=dict(keep_blocks),
        keep_rest=dict(keep_rest),
        keep_header=dict(keep_header),
        regexes=[str(k) for k in regexes],
        multiregexes=[str(k) for k in multiregexes],
    )

    return Patterns(
        tag_blocks=tag_blocks,
        keep_blocks=keep_blocks,
        keep_rest=keep_rest,
        keep_header=keep_header,
        regexes=regexes,
        multiregex_blocks=multiregex_blocks,
        multiregexes=multiregexes,
    )


def safe_file_read(file_path: Path) -> str:
    """Safely reads the content of a file if it exists.

    Args:
        file_path: Path to the file to read.

    Returns:
        The content of the file, or an empty string if the file does not exist.
    """
    if file_path.exists() and file_path.is_file():
        return read_text_utf8(file_path)
    return ''


def replace_text(
    template_content: str,
    local_content: str,
    anchors_dictionary: dict[str, str] | None = None,
    *,
    phase: str = 'pre-render',
) -> str:
    """Replaces tag blocks and regex patterns in the template content.

    Args:
        template_content: The content of the template file.
        local_content: The content of the local file to extract patterns from.
        anchors_dictionary: Optional dictionary of anchor replacements provided by
            configuration (maps tag name -> replacement text). If provided, values
            in this dict will be used to replace corresponding `## repolish-start[...]` blocks
            in the template. If not provided, the template's own block contents are
            preserved.
        phase: Directive phase to apply (`pre-render` or `after-render`).

    Returns:
        The modified template content with replaced tag blocks and regex patterns.
    """
    logger.debug(
        'starting_text_replacement',
        has_anchors=anchors_dictionary is not None,
        phase=phase,
    )
    if phase not in {'pre-render', 'after-render'}:
        msg = f'Unsupported preprocessing phase: {phase!r}'
        raise ValueError(msg)

    patterns = extract_patterns(template_content, phase=phase)

    # Build the replacement mapping for tag blocks. If an anchors dictionary is
    # provided, use its values to replace the corresponding tag blocks. Otherwise
    # fall back to the template's own block content (i.e. leave defaults).
    content = template_content
    tags_to_replace: dict[str, str] = {}
    if phase == 'pre-render':
        for tag, default_value in patterns.tag_blocks.items():
            if anchors_dictionary and tag in anchors_dictionary:
                tags_to_replace[tag] = anchors_dictionary[tag]
            else:
                tags_to_replace[tag] = default_value
        content = replace_tags_in_content(template_content, tags_to_replace)

    content = apply_keep_replacements(
        content,
        KeepPatterns(
            blocks={name: KeepBlockSpec(start=start, end=end) for name, (start, end) in patterns.keep_blocks.items()},
            rest={name: KeepMarkerSpec(marker=marker) for name, marker in patterns.keep_rest.items()},
            header={name: KeepMarkerSpec(marker=marker) for name, marker in patterns.keep_header.items()},
        ),
        local_content,
        phase=phase,
    )
    content = apply_regex_replacements(
        content,
        patterns.regexes,
        local_content,
        phase=phase,
    )
    content = apply_multiregex_replacements(
        content,
        patterns.multiregex_blocks,
        patterns.multiregexes,
        local_content,
        phase=phase,
    )
    result = content
    logger.debug(
        'text_replacement_completed',
        tag_blocks_replaced=len(tags_to_replace),
        regexes_applied=len(patterns.regexes),
        multiregexes_applied=len(patterns.multiregexes),
    )
    return result
