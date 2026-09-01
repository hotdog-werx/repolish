"""Directive-family registry — the extension point for new directive families.

A family is a module exposing an ``extract``/``apply`` pair:

- ``extract(content, phase, source_path) -> specs``: pull the family's
  directives out of template text for one phase.
- ``apply(content, specs, local_content, phase, source_path) -> str``: strip
  the family's directive lines for that phase and reconcile regions against
  the local file's content.

A family may also declare a ``ferry`` hook — data it wants delivered to a
consumer *past* the directive phases (for example, declarations for a phase
that runs after rendering). The file node
(:mod:`repolish.directives.files`) calls each ferrying family on the raw
template text and stamps the destination on :class:`FerriedItem`; the pipeline
carries the items through hydration and the apply session without knowing
what they are. Consumers read the families they know from
``SessionBundle.ferry``.

Adding a directive family means writing that module and adding one entry to
:data:`FAMILIES` below — nothing outside ``repolish.directives`` changes (a
ferrying family adds only its consumer on the receiving side).
Order matters: families apply in listing order against the accumulated
content.

Tag blocks (``repolish-start``/``repolish-end``) are deliberately *not* here:
they are the anchors primitive, driven by caller-supplied anchor dictionaries
in the pre-render phase rather than by local-file reconciliation, and are
handled by ``core.process_text`` itself.

Package-internal: not re-exported from ``repolish.directives`` (except
``FerriedItem``, which ferry consumers type against).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from repolish.directives.insert_zones import (
    InsertZoneSpec,
    apply_insert_zones,
    extract_insert_zones,
)
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
FerryFn = Callable[[str, str, str | None], tuple[object, ...]]
"""Signature of a family's ferry hook: ``(template_text, phase, source_path)``.

Same calling convention as :data:`ExtractFn`, but returns the opaque payloads
the family wants delivered to its consumer past the directive phases. Hooks
filter by phase themselves, exactly like ``extract``.
"""


@dataclass(frozen=True)
class FerriedItem:
    """One family payload traveling past the directive phases to its consumer.

    ``dest`` is the file the payload applies to — the local project file when
    the pair has one, else the staged/rendered file — stamped by
    :func:`repolish.directives.files.process_file` (the only place that knows
    the pairing). ``payload`` is the family's own type; the pipeline treats it
    as opaque.
    """

    dest: str
    payload: object


@dataclass(frozen=True)
class DirectiveFamily:
    """One directive family's extract/apply pair, keyed by family name."""

    name: str
    extract: ExtractFn
    apply: ApplyFn
    ferry: FerryFn | None = None


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


def _apply_insert_zones(
    content: str,
    specs: object,
    local_content: str,
    phase: str,
    source_path: str | None,
) -> str:
    return apply_insert_zones(
        content,
        cast('dict[str, InsertZoneSpec]', specs),
        local_content,
        phase=phase,
        source_path=source_path,
    )


FAMILIES: tuple[DirectiveFamily, ...] = (
    DirectiveFamily(
        name='keep',
        extract=extract_keep_patterns,
        apply=_apply_keep,
    ),
    DirectiveFamily(
        name='regex',
        extract=extract_regex_directives,
        apply=_apply_regex,
    ),
    DirectiveFamily(
        name='multiregex',
        extract=extract_multiregex_patterns,
        apply=_apply_multiregex,
    ),
    DirectiveFamily(
        name='insert-zone',
        extract=extract_insert_zones,
        apply=_apply_insert_zones,
    ),
)


def ferrying_families() -> tuple[DirectiveFamily, ...]:
    """Return the families that declared a ferry hook, in registry order."""
    return tuple(family for family in FAMILIES if family.ferry is not None)
