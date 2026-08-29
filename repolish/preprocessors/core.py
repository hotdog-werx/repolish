# ruff: noqa: I001
"""Core preprocessing utilities for templates.

This module provides the main functions for extracting patterns from templates,
replacing tags, and orchestrating the complete text replacement pipeline.
"""

import ast
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Protocol, TypeVar

from hotlog import get_logger

from repolish.preprocessors.anchors import replace_tags_in_content
from repolish.preprocessors.directive_phase import (
    PreprocessPhase,
    split_directive_tag as _split_directive_tag,
)
from repolish.preprocessors.directives import (
    KEEP_BLOCK_DIRECTIVE_RE,
    KEEP_HEADER_DIRECTIVE_RE,
    KEEP_REST_DIRECTIVE_RE,
    MULTIREGEX_BLOCK_DIRECTIVE_RE,
    MULTIREGEX_DIRECTIVE_RE,
    REGEX_DIRECTIVE_RE,
    TAG_BLOCK_RE,
)
from repolish.preprocessors.keep import (
    apply_keep_replacements,
    KeepBlockSpec,
    KeepMarkerSpec,
    KeepPatterns,
)
from repolish.preprocessors.multiregex import apply_multiregex_replacements
from repolish.preprocessors.regex import apply_regex_replacements

logger = get_logger(__name__)

T = TypeVar('T')


class PostPass(Protocol):
    """A text transform applied after the built-in directive passes.

    Lets orchestrators (e.g. the apply session) extend a phase with extra
    reconciliation — such as insertion-marker adoption — without the
    preprocessors package importing those features itself.
    """

    def __call__(
        self,
        content: str,
        local_content: str,
        *,
        source_path: str | None = None,
    ) -> str:
        """Return *content* after reconciling it with *local_content*."""
        ...


@dataclass
class Patterns:
    """Container for extracted patterns from content."""

    tag_blocks: dict[str, str]
    keep_blocks: dict[str, tuple[str, str | None, str | None]]
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


_TAG_PATTERN = TAG_BLOCK_RE

_REGEX_PATTERN_DEF = _PatternDefinition[str](
    pattern=REGEX_DIRECTIVE_RE,
    parse_value=lambda pattern: pattern,
)

_KEEP_BLOCK_PATTERN_DEF = _PatternDefinition[tuple[str, str | None, str | None]](
    pattern=KEEP_BLOCK_DIRECTIVE_RE,
    parse_value=lambda start_raw, end_mode, end_raw: _parse_keep_block_bounds(
        start_raw,
        end_mode,
        end_raw,
    ),
)

_KEEP_REST_PATTERN_DEF = _PatternDefinition[str](
    pattern=KEEP_REST_DIRECTIVE_RE,
    parse_value=lambda marker_raw: _parse_keep_literal(marker_raw),
)

_KEEP_HEADER_PATTERN_DEF = _PatternDefinition[str](
    pattern=KEEP_HEADER_DIRECTIVE_RE,
    parse_value=lambda marker_raw: _parse_keep_literal(marker_raw),
)

_MULTIREGEX_BLOCK_PATTERN_DEF = _PatternDefinition[str](
    pattern=MULTIREGEX_BLOCK_DIRECTIVE_RE,
    parse_value=lambda pattern: pattern,
)

_MULTIREGEX_PATTERN_DEF = _PatternDefinition[str](
    pattern=MULTIREGEX_DIRECTIVE_RE,
    parse_value=lambda pattern: pattern,
)


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


def _parse_keep_block_bounds(
    start_raw: str,
    end_mode: str,
    end_raw: str,
) -> tuple[str, str | None, str | None]:
    """Parse keep-block bounds supporting literal `end` and `end-regex`."""
    start = _parse_keep_literal(start_raw)
    end_value = _parse_keep_literal(end_raw)
    if end_mode == 'end':
        return (start, end_value, None)
    return (start, None, end_value)


def _extract_tag_blocks(content: str) -> dict[str, str]:
    """Extract repolish-start/end blocks preserving only inner content."""
    raw_tag_blocks = dict(_TAG_PATTERN.findall(content))
    return {key: value.strip('\n') for key, value in raw_tag_blocks.items()}


def _extract_directive_map(
    content: str,
    definition: _PatternDefinition[T],
    *,
    phase: str,
    source_path: str | None = None,
) -> dict[str, T]:
    """Extract a phase-filtered directive map keyed by logical directive name."""
    result: dict[str, T] = {}
    for match in definition.pattern.findall(content):
        raw_name, *values = match
        name, directive_phase = _split_directive_tag(
            raw_name,
            source_path=source_path,
        )
        if not _is_phase_selected(directive_phase, phase):
            continue
        result[name] = definition.parse_value(*values)
    return result


def extract_patterns(
    content: str,
    *,
    phase: PreprocessPhase = PreprocessPhase.PRE_RENDER,
    source_path: str | None = None,
) -> Patterns:
    """Extracts text blocks and regex patterns from the given content.

    Args:
        content: The input string containing text blocks and regex patterns.
        phase: Directive phase to extract (`pre-render` or `after-render`).
        source_path: Optional template path used for contextual warning logs.

    Returns:
        A Patterns object containing extracted tag blocks and regexes.
    """
    selected_phase = phase.value

    tag_blocks = _extract_tag_blocks(content)
    keep_blocks = _extract_directive_map(
        content,
        _KEEP_BLOCK_PATTERN_DEF,
        phase=selected_phase,
        source_path=source_path,
    )
    keep_rest = _extract_directive_map(
        content,
        _KEEP_REST_PATTERN_DEF,
        phase=selected_phase,
        source_path=source_path,
    )
    keep_header = _extract_directive_map(
        content,
        _KEEP_HEADER_PATTERN_DEF,
        phase=selected_phase,
        source_path=source_path,
    )
    regexes = _extract_directive_map(
        content,
        _REGEX_PATTERN_DEF,
        phase=selected_phase,
        source_path=source_path,
    )
    multiregex_blocks = _extract_directive_map(
        content,
        _MULTIREGEX_BLOCK_PATTERN_DEF,
        phase=selected_phase,
        source_path=source_path,
    )
    multiregexes = _extract_directive_map(
        content,
        _MULTIREGEX_PATTERN_DEF,
        phase=selected_phase,
        source_path=source_path,
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
        return file_path.read_text(encoding='utf-8')
    return ''


def preprocess_text(  # noqa: PLR0913 - canonical entry point, params are the public contract
    template_content: str,
    local_content: str,
    anchors_dictionary: dict[str, str] | None = None,
    *,
    phase: PreprocessPhase = PreprocessPhase.PRE_RENDER,
    source_path: str | None = None,
    post_passes: Iterable[PostPass] | None = None,
) -> str:
    """Replaces tag blocks and regex patterns in the template content.

    This is the canonical pure text-transform entry point of the preprocessors
    package: template text in, processed text out, with no file I/O.

    Args:
        template_content: The content of the template file.
        local_content: The content of the local file to extract patterns from.
        anchors_dictionary: Optional dictionary of anchor replacements provided by
            configuration (maps tag name -> replacement text). If provided, values
            in this dict will be used to replace corresponding `## repolish-start[...]` blocks
            in the template. If not provided, the template's own block contents are
            preserved.
        phase: Directive phase to apply (`pre-render` or `after-render`).
        source_path: Optional template path used for contextual warning logs.
        post_passes: Extra transforms applied after the built-in directive
            passes, each receiving ``(content, local_content, *, source_path)``.
            When ``None``, the legacy default applies: the ``after-render``
            phase additionally adopts local insertion markers. Pass an explicit
            iterable (possibly empty) to control the passes yourself.

    Returns:
        The modified template content with replaced tag blocks and regex patterns.
    """
    selected_phase = phase.value

    logger.debug(
        'starting_text_replacement',
        has_anchors=anchors_dictionary is not None,
        phase=selected_phase,
    )

    patterns = extract_patterns(
        template_content,
        phase=phase,
        source_path=source_path,
    )

    # Build the replacement mapping for tag blocks. If an anchors dictionary is
    # provided, use its values to replace the corresponding tag blocks. Otherwise
    # fall back to the template's own block content (i.e. leave defaults).
    content = template_content
    tags_to_replace: dict[str, str] = {}
    if selected_phase == PreprocessPhase.PRE_RENDER.value:
        for tag, default_value in patterns.tag_blocks.items():
            if anchors_dictionary and tag in anchors_dictionary:
                tags_to_replace[tag] = anchors_dictionary[tag]
            else:
                tags_to_replace[tag] = default_value
        content = replace_tags_in_content(template_content, tags_to_replace)

    content = apply_keep_replacements(
        content,
        KeepPatterns(
            blocks={
                name: KeepBlockSpec(
                    start=start,
                    end=end,
                    end_regex=end_regex,
                )
                for name, (
                    start,
                    end,
                    end_regex,
                ) in patterns.keep_blocks.items()
            },
            rest={name: KeepMarkerSpec(marker=marker) for name, marker in patterns.keep_rest.items()},
            header={name: KeepMarkerSpec(marker=marker) for name, marker in patterns.keep_header.items()},
        ),
        local_content,
        phase=selected_phase,
        source_path=source_path,
    )
    content = apply_regex_replacements(
        content,
        patterns.regexes,
        local_content,
        phase=selected_phase,
    )
    content = apply_multiregex_replacements(
        content,
        patterns.multiregex_blocks,
        patterns.multiregexes,
        local_content,
        phase=selected_phase,
    )
    if post_passes is None and selected_phase == PreprocessPhase.AFTER_RENDER.value:
        # Legacy default: preserve developer-chosen insertion function/args
        # from the local file. Runs only after render so loop-generated markers
        # are fully concrete. Imported lazily so the preprocessors package has
        # no static dependency on repolish.insertions — orchestrators should
        # pass post_passes explicitly instead (see commands/apply/session.py).
        from repolish.insertions.adoption import (  # noqa: PLC0415 - legacy default, keeps insertions out of the static dependency graph
            adopt_local_insertion_markers,
        )

        content = adopt_local_insertion_markers(
            content,
            local_content,
            source_path=source_path,
        )
    elif post_passes:
        for post_pass in post_passes:
            content = post_pass(
                content,
                local_content,
                source_path=source_path,
            )
    result = content
    logger.debug(
        'text_replacement_completed',
        tag_blocks_replaced=len(tags_to_replace),
        regexes_applied=len(patterns.regexes),
        multiregexes_applied=len(patterns.multiregexes),
    )
    return result


def replace_text(
    template_content: str,
    local_content: str,
    anchors_dictionary: dict[str, str] | None = None,
    *,
    phase: PreprocessPhase = PreprocessPhase.PRE_RENDER,
    source_path: str | None = None,
) -> str:
    """Backward-compatible alias for :func:`preprocess_text`.

    Kept for existing callers; new code should use :func:`preprocess_text`,
    which additionally accepts ``post_passes``.
    """
    return preprocess_text(
        template_content,
        local_content,
        anchors_dictionary,
        phase=phase,
        source_path=source_path,
    )


def strip_directives(
    content: str,
    *,
    phase: PreprocessPhase = PreprocessPhase.PRE_RENDER,
    source_path: str | None = None,
) -> str:
    """Strip directive lines and resolve defaults against an empty local file.

    Intended for tooling (e.g. lint) that needs directive-free template text
    before further parsing. Tag blocks keep their template defaults and keep
    regions resolve from the template itself, since there is no local content
    to extract overrides from.
    """
    return preprocess_text(content, '', phase=phase, source_path=source_path)
