"""Fill provider-branded insertion zones declared by template directives.

Templates declare zones with ``repolish:insert[name] start=... end=...``
directives (the grammar and directive-line stripping live in
``repolish.directives``); the declaration ferry hands the insertion phase one
``InsertZoneDeclaration`` per template that carried the directive. The zone
region itself is bounded by branded markers whose opening line can carry
function arguments::

    <!-- generated:badges:on my-org/my-repo style=flat -->
    ...template default body...
    <!-- generated:badges:off -->

Filling means: for each zone occurrence in the target file, resolve the
renderer (the declaration's explicit ``function``, or the zone name, looked
up in the provider registry) and splice its output over the block body.
Fallbacks always keep the *template default* body rather than failing the
file — the default is authored content, never to be swallowed:

- unknown function → diagnostic, default kept
- disabled function/tag (``overrides.insertions``) → the provider wrapper
  already returns ``block.body`` unchanged, so the default survives while
  reporting still sees the disable via the synthetic blocks returned here
- renderer raised / malformed opening args → diagnostic, default kept

Opening-marker args are *not* adopted here: the directive family's ``apply``
pass already spliced the developer's opening marker into the file before the
insertion phase ran, so by the time filling happens the args are the
developer's.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from hotlog import get_logger

from repolish.insertions.disabled import resolve_renderer_for_function
from repolish.insertions.models import InsertionBlock
from repolish.insertions.writer import (
    WriteDiagnostic,
    call_registered_renderer,
)
from repolish.marker_kit import find_prefixed_bounded_regions

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from repolish.directives import FerriedItem, InsertZoneDeclaration
    from repolish.marker_kit import PrefixedRegion

logger = get_logger(__name__)


@dataclass(frozen=True)
class ZoneFillOutcome:
    """The rewritten document plus zone-level metadata for reporting.

    ``blocks`` are synthetic :class:`InsertionBlock` records (one per zone
    occurrence encountered) so the command layer can reuse its provider
    attribution and disabled-override accounting for zones.
    """

    text: str
    blocks: list[InsertionBlock] = field(default_factory=list)
    diagnostics: list[WriteDiagnostic] = field(default_factory=list)
    functions: tuple[str, ...] = ()
    total_blocks: int = 0
    failed_blocks: int = 0


def collect_insert_zones(
    items: Iterable[FerriedItem],
) -> dict[str, tuple[InsertZoneDeclaration, ...]]:
    """Group the insert-zone family's ferried items by project-relative dest.

    The session already relativized every dest against the project root, so
    grouping is all that is left: the drivers key on the same ``rel_path``
    they use for file insertions. Each payload is the family's
    :class:`~repolish.directives.InsertZoneDeclaration`.
    """
    merged: dict[str, list[InsertZoneDeclaration]] = {}
    for item in items:
        declaration = cast('InsertZoneDeclaration', item.payload)
        merged.setdefault(item.dest, []).append(declaration)
    return {dest: tuple(declarations) for dest, declarations in merged.items()}


def _resolve_zone_fill(
    declaration: InsertZoneDeclaration,
    region: PrefixedRegion,
    body: str,
    registry: Mapping,
    file_path: str,
) -> tuple[InsertionBlock, list[WriteDiagnostic], list[str] | None]:
    """Resolve one zone occurrence to a splice payload.

    Returns ``(block, diagnostics, new_body_lines)``: the synthetic block for
    reporting, any diagnostics produced, and the replacement body lines — or
    ``None`` when the template default body stays (unknown function, renderer
    failure, malformed opening args; disabled renderers simply return the
    body so the default survives through the normal call path).
    """
    function = declaration.spec.function or declaration.name
    diagnostics: list[WriteDiagnostic] = []

    # Drop a trailing comment close (``-->``) — the args are the part of the
    # opening comment line that follows the start marker.
    raw_args = region.opening_args
    if raw_args.endswith('-->'):
        raw_args = raw_args[: -len('-->')].rstrip()

    args: tuple[str, ...] = ()
    if raw_args.strip():
        try:
            args = tuple(shlex.split(raw_args))
        except ValueError as exc:
            diagnostics.append(
                WriteDiagnostic(
                    tag=declaration.name,
                    message=(
                        f'insertion zone {declaration.name!r}: malformed '
                        f'opening marker args — template default kept ({exc})'
                    ),
                    exception=exc,
                ),
            )
            return (
                InsertionBlock(
                    tag=declaration.name,
                    function=function,
                    body=body,
                    file_path=file_path,
                ),
                diagnostics,
                None,
            )

    block = InsertionBlock(
        tag=declaration.name,
        function=function,
        args=args,
        body=body,
        file_path=file_path,
    )

    if resolve_renderer_for_function(registry, function) is None:
        diagnostics.append(
            WriteDiagnostic(
                tag=declaration.name,
                message=(
                    f'No renderer registered for insertion zone '
                    f'{declaration.name!r} (function {function!r}) — '
                    'template default kept.'
                ),
            ),
        )
        return block, diagnostics, None

    try:
        rendered = call_registered_renderer(registry, block)
    except Exception as exc:  # noqa: BLE001 - zone failures keep the template default, never the file
        diagnostics.append(
            WriteDiagnostic(
                tag=declaration.name,
                message=str(exc),
                exception=exc,
            ),
        )
        return block, diagnostics, None

    new_body = rendered if not rendered or rendered.endswith('\n') else f'{rendered}\n'
    return block, diagnostics, [new_body] if new_body else []


@dataclass
class _FillPlan:
    """Mutable accumulators shared by the per-declaration fill passes."""

    blocks: list[InsertionBlock] = field(default_factory=list)
    diagnostics: list[WriteDiagnostic] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    splices: list[tuple[int, int, list[str]]] = field(default_factory=list)


def _plan_declaration_fills(
    declaration: InsertZoneDeclaration,
    lines: list[str],
    registry: Mapping,
    file_path: str,
    plan: _FillPlan,
) -> int:
    """Resolve every occurrence of one zone, appending to *plan*.

    Returns how many occurrences of the declaration were found (0 when the
    markers are absent from the file — a debug-worthy no-op, not an error).
    """
    regions = find_prefixed_bounded_regions(lines, declaration.spec.boundary)
    if not regions:
        logger.debug(
            'insert_zone_fill_region_not_found',
            name=declaration.name,
            file_path=file_path,
        )
        return 0
    for region in regions:
        block, region_diagnostics, new_body = _resolve_zone_fill(
            declaration,
            region,
            ''.join(lines[region.start + 1 : region.end]),
            registry,
            file_path,
        )
        plan.blocks.append(block)
        plan.functions.append(block.function)
        plan.diagnostics.extend(region_diagnostics)
        if new_body is not None:
            plan.splices.append((region.start + 1, region.end, new_body))
    return len(regions)


def fill_insert_zones(
    text: str,
    declarations: Iterable[InsertZoneDeclaration],
    registry: Mapping,
    *,
    file_path: str = '',
) -> ZoneFillOutcome:
    """Fill every declared zone occurrence in *text* against *registry*.

    Unknown/disabled/failing renderers leave the zone body untouched (the
    template default) and record a diagnostic, mirroring keep-block's
    never-fail-the-file contract. Repeated zones with the same markers are
    all filled; each occurrence becomes one synthetic block for reporting.
    """
    zones = list(declarations)
    if not zones:
        return ZoneFillOutcome(text=text)

    lines = text.splitlines(keepends=True)
    plan = _FillPlan()

    total = sum(_plan_declaration_fills(declaration, lines, registry, file_path, plan) for declaration in zones)

    # Apply bottom-up so splice indices stay valid for earlier zones.
    for body_start, body_end, body_lines in sorted(plan.splices, reverse=True):
        lines[body_start:body_end] = body_lines

    return ZoneFillOutcome(
        text=''.join(lines),
        blocks=plan.blocks,
        diagnostics=plan.diagnostics,
        functions=tuple(plan.functions),
        total_blocks=total,
        failed_blocks=len(plan.diagnostics),
    )
