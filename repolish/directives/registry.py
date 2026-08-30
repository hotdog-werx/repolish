"""Directive-family registry — the extension point for new directive families.

A family is a module exposing an ``extract``/``apply`` pair:

- ``extract(content, phase, source_path) -> specs``: pull the family's
  directives out of template text for one phase.
- ``apply(content, specs, local_content, phase, source_path) -> str``: strip
  the family's directive lines for that phase and reconcile regions against
  the local file's content.

Adding a directive family means writing that module and adding one entry to
:data:`FAMILIES` below — nothing outside ``repolish.directives`` changes.
Order matters: families apply in listing order against the accumulated
content.

Tag blocks (``repolish-start``/``repolish-end``) are deliberately *not* here:
they are the anchors primitive, driven by caller-supplied anchor dictionaries
in the pre-render phase rather than by local-file reconciliation, and are
handled by ``core.process_text`` itself.

Package-internal: not re-exported from ``repolish.directives``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from repolish.directives.keep import (
    KeepPatterns,
    apply_keep_replacements,
    extract_keep_patterns,
)
from repolish.directives.multiregex import (
    MultiregexPatterns,
    apply_multiregex_replacements,
    extract_multiregex_patterns,
)
from repolish.directives.regex import (
    apply_regex_replacements,
    extract_regex_directives,
)

ExtractFn = Callable[[str, str, str | None], object]
ApplyFn = Callable[[str, object, str, str, str | None], str]


@dataclass(frozen=True)
class DirectiveFamily:
    """One directive family's extract/apply pair, keyed by family name."""

    name: str
    extract: ExtractFn
    apply: ApplyFn


def _apply_keep(
    content: str,
    specs: object,
    local_content: str,
    phase: str,
    source_path: str | None,
) -> str:
    return apply_keep_replacements(
        content,
        cast('KeepPatterns', specs),
        local_content,
        phase=phase,
        source_path=source_path,
    )


def _apply_regex(
    content: str,
    specs: object,
    local_content: str,
    phase: str,
    source_path: str | None,  # noqa: ARG001 - registry apply signature is uniform
) -> str:
    return apply_regex_replacements(
        content,
        cast('dict[str, str]', specs),
        local_content,
        phase=phase,
    )


def _apply_multiregex(
    content: str,
    specs: object,
    local_content: str,
    phase: str,
    source_path: str | None,  # noqa: ARG001 - registry apply signature is uniform
) -> str:
    patterns = cast('MultiregexPatterns', specs)
    return apply_multiregex_replacements(
        content,
        patterns.blocks,
        patterns.regexes,
        local_content,
        phase=phase,
    )


FAMILIES: tuple[DirectiveFamily, ...] = (
    DirectiveFamily(name='keep', extract=extract_keep_patterns, apply=_apply_keep),
    DirectiveFamily(name='regex', extract=extract_regex_directives, apply=_apply_regex),
    DirectiveFamily(
        name='multiregex',
        extract=extract_multiregex_patterns,
        apply=_apply_multiregex,
    ),
)
