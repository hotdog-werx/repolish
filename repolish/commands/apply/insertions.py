"""Apply insertion registries to non-owned files after file writes."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from hotlog import get_logger

from repolish.commands.apply.options import InsertionFileResult
from repolish.config.paused import is_paused
from repolish.hydration.misc import get_source_str_from_mapping
from repolish.insertions import (
    DisabledDiagnosticEntry,
    DisabledInsertionEntry,
    ErrorDiagnosticEntry,
    InsertionReport,
    collect_disabled_entries,
    collect_insert_zones,
    is_provider_owner,
)
from repolish.insertions.files import (
    render_insertions_file,
    render_insertions_text,
)
from repolish.insertions.parser import InsertionBlock, parse_text
from repolish.marker_kit import read_text_or_none, write_mode_preserved
from repolish.utils import build_unified_diff, path_slug

if TYPE_CHECKING:
    from repolish.directives import InsertZoneDeclaration
    from repolish.insertions.writer import WriteBackResult
    from repolish.providers import SessionBundle

logger = get_logger(__name__)


@dataclass
class _ProviderInsertionContext:
    """State object for tracking insertion processing across providers."""

    rel_path: str
    registry: dict
    provider_ids: list[str]
    pid_to_alias: dict[str, str] | None
    reports_dir: Path
    zone_declarations: tuple[InsertZoneDeclaration, ...] = ()
    """Insert zones declared for this file by template directives (empty when
    the file carries no zones)."""
    zone_registry: dict = field(default_factory=dict)
    """Registry zone fills resolve against: the session-wide registry with
    this file's entries layered on top, so per-file config-disabled renderers
    keep applying to zones while every contributed function stays reachable."""
    zone_blocks: tuple[InsertionBlock, ...] = ()
    """Synthetic blocks from the zone fill, set after the drive call for
    provider attribution in reporting."""

    results: dict[str, InsertionFileResult] = field(default_factory=dict)
    provider_results: dict[str, dict[str, InsertionFileResult]] = field(
        default_factory=dict,
    )


@dataclass
class _StagedCheckResult:
    """Result of staged check-mode comparison for one file."""

    handled: bool
    diff: tuple[str, str] | None = None


def _get_blocks_for_provider(
    text: str,
    provider_alias: str,
    rel_path: str = '',
    *,
    is_first_provider: bool = False,
) -> list[InsertionBlock]:
    """Get insertion blocks that belong to a specific provider."""
    parsed = parse_text(text, file_path=rel_path)
    return [
        b
        for b in parsed.blocks
        if is_provider_owner(
            b.function,
            provider_alias,
            is_first_provider=is_first_provider,
        )
    ]


def _build_tag_to_func_map(blocks: list[InsertionBlock]) -> dict[str, str]:
    """Build a mapping from block tags to function names."""
    return {b.tag: b.function for b in blocks}


def _filter_provider_functions(
    functions: tuple[str, ...],
    provider_alias: str,
    *,
    is_first_provider: bool = False,
) -> list[str]:
    """Filter functions to only those belonging to a specific provider."""
    return [
        f
        for f in functions
        if is_provider_owner(
            f,
            provider_alias,
            is_first_provider=is_first_provider,
        )
    ]


def _filter_provider_diagnostics(
    diagnostics: list,
    tag_to_func: dict[str, str],
    provider_alias: str,
    *,
    is_first_provider: bool = False,
) -> tuple[int, list]:
    """Filter diagnostics to only those belonging to a specific provider.

    Returns:
        Tuple of (failed_count, filtered_diagnostics)
    """
    failed = 0
    filtered = []
    for d in diagnostics:
        tag = d.tag if isinstance(d.tag, str) else ''
        func_name = tag_to_func.get(tag, tag)
        if is_provider_owner(
            func_name,
            provider_alias,
            is_first_provider=is_first_provider,
        ):
            failed += 1
            filtered.append(d)
    return failed, filtered


def _process_provider_insertions(
    ctx: _ProviderInsertionContext,
    original_text: str,
    result: WriteBackResult,
    tag_to_func: dict[str, str],
    disabled_entries: list[DisabledInsertionEntry],
) -> tuple[InsertionFileResult, dict[str, InsertionFileResult]]:
    """Process insertions for each provider and write reports."""
    provider_results: dict[str, InsertionFileResult] = {}
    report_paths: list[str] = []

    for idx, provider_id in enumerate(ctx.provider_ids):
        provider_alias = ctx.pid_to_alias.get(provider_id, provider_id) if ctx.pid_to_alias else provider_id
        is_first_provider = idx == 0

        provider_blocks = _get_blocks_for_provider(
            original_text,
            provider_alias,
            ctx.rel_path,
            is_first_provider=is_first_provider,
        )
        provider_blocks.extend(
            block
            for block in ctx.zone_blocks
            if is_provider_owner(
                block.function,
                provider_alias,
                is_first_provider=is_first_provider,
            )
        )
        provider_functions = _filter_provider_functions(
            result.functions,
            provider_alias,
            is_first_provider=is_first_provider,
        )
        provider_failed, provider_diagnostics = _filter_provider_diagnostics(
            result.diagnostics,
            tag_to_func,
            provider_alias,
            is_first_provider=is_first_provider,
        )
        provider_disabled = [
            entry
            for entry in disabled_entries
            if is_provider_owner(
                entry.function,
                provider_alias,
                is_first_provider=is_first_provider,
            )
        ]

        report_file = ctx.reports_dir / f'insertions.{path_slug(ctx.rel_path)}.{provider_alias}.json'
        report = InsertionReport(
            file=ctx.rel_path,
            source_provider=provider_id,
            provider_alias=provider_alias,
            total_blocks=len(provider_blocks),
            failed_blocks=provider_failed,
            disabled_blocks=len(provider_disabled),
            functions=provider_functions,
            diagnostics=[
                *[ErrorDiagnosticEntry.from_diagnostic(d) for d in provider_diagnostics],
                *[DisabledDiagnosticEntry.from_entry(e) for e in provider_disabled],
            ],
        )
        report_file.write_text(
            json.dumps(report.model_dump(), indent=2),
            encoding='utf-8',
        )

        report_paths.append(report_file.as_posix())

        provider_results[provider_alias] = InsertionFileResult(
            total_blocks=len(provider_blocks),
            failed_blocks=provider_failed,
            disabled_blocks=len(provider_disabled),
            functions=tuple(provider_functions),
            diagnostics=tuple(d.message for d in provider_diagnostics),
            disabled_messages=tuple(entry.message for entry in provider_disabled),
            report_path=report_file.as_posix(),
        )

    aggregated = InsertionFileResult(
        total_blocks=result.total_blocks,
        failed_blocks=result.failed_blocks,
        disabled_blocks=len(disabled_entries),
        functions=result.functions,
        diagnostics=tuple(diag.message for diag in result.diagnostics),
        disabled_messages=tuple(entry.message for entry in disabled_entries),
        report_path=report_paths[0] if report_paths else None,
    )

    return aggregated, provider_results


def _stage_file_insertions(
    ctx: _ProviderInsertionContext,
    staged_root: Path,
    source_text: str,
) -> tuple[InsertionFileResult, dict[str, dict[str, InsertionFileResult]]]:
    """Render *ctx*'s file insertions and write the result into the render tree."""
    rendered, zone_blocks = render_insertions_text(
        source_text,
        ctx.registry,
        file_path=ctx.rel_path,
        zone_declarations=ctx.zone_declarations,
        zone_registry=ctx.zone_registry,
    )
    staged_file = staged_root / ctx.rel_path
    staged_file.parent.mkdir(parents=True, exist_ok=True)
    if staged_file.exists():
        write_mode_preserved(staged_file, rendered.text)
    else:
        staged_file.write_text(rendered.text, encoding='utf-8')
    ctx.zone_blocks = zone_blocks

    parsed = parse_text(source_text, file_path=ctx.rel_path)
    all_blocks = [*parsed.blocks, *zone_blocks]
    # Zones resolve (and can be disabled) through the session-wide registry;
    # developer-authored markers stay on the file's allowlist.
    zone_registry = ctx.zone_registry or ctx.registry
    disabled_entries = [
        *collect_disabled_entries(parsed.blocks, ctx.registry),
        *collect_disabled_entries(zone_blocks, zone_registry),
    ]

    if rendered.total_blocks == 0:
        return (
            InsertionFileResult(
                total_blocks=0,
                failed_blocks=0,
                functions=(),
                diagnostics=(),
            ),
            {ctx.rel_path: {}},
        )

    tag_to_func = _build_tag_to_func_map(all_blocks)
    aggregated, per_provider = _process_provider_insertions(
        ctx,
        source_text,
        rendered,
        tag_to_func,
        disabled_entries,
    )

    if aggregated.diagnostics:
        logger.warning(
            'file_insertions_render_failed',
            file=ctx.rel_path,
            diagnostics=list(aggregated.diagnostics),
            _display_level=1,
        )

    return aggregated, {ctx.rel_path: per_provider}


def _should_skip_file(
    rel_path: str,
    base_dir: Path,
    paused_files: frozenset[str] | None = None,
) -> bool:
    """Check if a file should be skipped for insertion processing."""
    if paused_files and is_paused(rel_path, paused_files):
        return True
    target = base_dir / rel_path
    return not target.exists() or target.is_dir()


def _merge_provider_results(
    provider_results: dict[str, dict[str, InsertionFileResult]],
    rel_path: str,
    file_provider_results: dict[str, InsertionFileResult],
) -> None:
    """Merge per-provider results into the top-level dict."""
    for provider_alias, file_result in file_provider_results.items():
        provider_results.setdefault(provider_alias, {})[rel_path] = file_result


def _zone_map(
    providers: SessionBundle,
) -> dict[str, tuple[InsertZoneDeclaration, ...]]:
    """Group the insert-zone family's ferried declarations by destination.

    The apply session delivers every family's data on ``providers.ferry``
    before any insertion driver runs; this is the drivers' one read of it.
    """
    return collect_insert_zones(providers.ferry.get('insert-zone', ()))


def _zone_registry(
    providers: SessionBundle,
    rel_path: str,
) -> dict:
    """Zone resolution registry: session-wide, with the file's entries on top.

    Zones are provider-authored, so they may resolve any contributed function —
    the per-file allowlist governs developer-authored markers only. The file's
    own entries win their keys so config-disabled renderers (per-file
    overrides) keep applying to that file's zones.
    """
    return {
        **providers.insertion_registry,
        **providers.file_insertions.get(rel_path, {}),
    }


def _mapped_staged_source(
    providers: SessionBundle,
    staged_root: Path,
    rel_path: str,
) -> Path | None:
    """Return the staged render of *rel_path*'s mapped source, when mapped.

    Mirrors the staged-source lookup the apply copy uses (including the
    ``_repolish.`` filename-prefix fallback), so a mapped destination's
    insertions render on fresh template output rather than the stale project
    file.
    """
    source = providers.file_mappings.get(rel_path)
    if source is None:
        return None
    source_str = get_source_str_from_mapping(source)
    if not source_str:
        return None

    source_file = staged_root / source_str
    if source_file.exists():
        return source_file
    cand = Path(source_str)
    prefixed = staged_root / cand.parent / ('_repolish.' + cand.name)
    if prefixed.exists():
        return prefixed
    return None


def _staged_source_text(
    providers: SessionBundle,
    base_dir: Path,
    staged_root: Path,
    rel_path: str,
) -> str | None:
    """Return the base text for staging *rel_path*'s insertions.

    Mapped destinations start from their freshly rendered staged source;
    auto-staged files start from their staged copy. A developer-owned file is
    copied into the render tree first so insertions and post-process commands
    operate on the staged copy, never the project file.
    """
    staged_file = staged_root / rel_path

    mapped_source = _mapped_staged_source(providers, staged_root, rel_path)
    if mapped_source is not None:
        mapped_text = read_text_or_none(mapped_source)
        if mapped_text is not None:
            return mapped_text

    staged_text = read_text_or_none(staged_file)
    if staged_text is not None:
        return staged_text

    project_file = base_dir / rel_path
    project_text = read_text_or_none(project_file)
    if project_text is None:
        return None
    staged_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(project_file, staged_file)
    return project_text


def stage_registered_insertions(
    providers: SessionBundle,
    base_dir: Path,
    setup_output: Path,
    pid_to_alias: dict[str, str] | None = None,
) -> tuple[
    dict[str, InsertionFileResult],
    dict[str, dict[str, InsertionFileResult]],
    frozenset[str],
]:
    """Render insertion targets into the render tree for apply/check parity.

    Every insertion target is materialized under the render tree — mapped
    destinations from their freshly rendered staged source, developer-owned
    files copied in from the project tree — so post-process commands run once
    over final content and the project tree is only ever touched by the final
    copy. Files carrying template-declared insert zones are processed even
    when no provider registered ``repolish:on`` insertions for them.

    Returns ``(file_results, provider_results, staged_dests)``.
    *staged_dests* lists the destinations materialized in the render tree;
    callers pass it to ``apply_generated_output`` so the copy step knows
    which staged files are insertion output.
    """
    staged_root = setup_output / 'repolish'
    results: dict[str, InsertionFileResult] = {}
    provider_results: dict[str, dict[str, InsertionFileResult]] = {}
    reports_dir = base_dir / '.repolish' / '_' / 'insertions'
    reports_dir.mkdir(parents=True, exist_ok=True)
    paused_files = providers.paused_files
    zone_map = _zone_map(providers)
    staged_dests: set[str] = set()

    for rel_path in dict.fromkeys((*providers.file_insertions, *zone_map)):
        if paused_files and is_paused(rel_path, paused_files):
            continue
        source_text = _staged_source_text(
            providers,
            base_dir,
            staged_root,
            rel_path,
        )
        if source_text is None:
            continue

        ctx = _ProviderInsertionContext(
            rel_path=rel_path,
            registry=providers.file_insertions.get(rel_path, {}),
            provider_ids=providers.insertion_sources.get(rel_path, []),
            pid_to_alias=pid_to_alias,
            reports_dir=reports_dir,
            zone_declarations=zone_map.get(rel_path, ()),
            zone_registry=_zone_registry(providers, rel_path),
        )

        aggregated, file_provider_results = _stage_file_insertions(
            ctx,
            staged_root,
            source_text,
        )
        results[rel_path] = aggregated
        _merge_provider_results(
            provider_results,
            rel_path,
            file_provider_results[ctx.rel_path],
        )
        staged_dests.add(rel_path)

    return results, provider_results, frozenset(staged_dests)


def check_registered_insertions(
    providers: SessionBundle,
    base_dir: Path,
    setup_output: Path | None = None,
) -> list[tuple[str, str]]:
    """Return insertion drift diffs for check mode without mutating files."""
    diffs: list[tuple[str, str]] = []
    paused_files = providers.paused_files
    zone_map = _zone_map(providers)

    for rel_path in dict.fromkeys((*providers.file_insertions, *zone_map)):
        registry = providers.file_insertions.get(rel_path, {})
        if not _should_skip_file(rel_path, base_dir, paused_files):
            target = base_dir / rel_path
            staged_result = _staged_check_result(
                rel_path=rel_path,
                target=target,
                setup_output=setup_output,
            )
            if staged_result.handled and staged_result.diff is not None:
                diffs.append(staged_result.diff)
            elif (
                not staged_result.handled
                and (
                    rendered_diff := _rendered_diff_if_any(
                        rel_path=rel_path,
                        target=target,
                        registry=registry,
                        zone_declarations=zone_map.get(rel_path, ()),
                        zone_registry=_zone_registry(providers, rel_path),
                    )
                )
                is not None
            ):
                diffs.append(rendered_diff)

    return diffs


def _staged_check_result(
    *,
    rel_path: str,
    target: Path,
    setup_output: Path | None,
) -> _StagedCheckResult:
    """Return whether staged comparison handled this file and any resulting diff."""
    if setup_output is None:
        return _StagedCheckResult(handled=False)

    staged_file = setup_output / 'repolish' / rel_path
    rendered = read_text_or_none(staged_file)
    if rendered is None:
        return _StagedCheckResult(handled=False)

    current = target.read_text(encoding='utf-8')
    if current == rendered:
        return _StagedCheckResult(handled=True)
    return _StagedCheckResult(
        handled=True,
        diff=(rel_path, build_unified_diff(rel_path, current, rendered)),
    )


def _rendered_diff_if_any(
    *,
    rel_path: str,
    target: Path,
    registry: dict,
    zone_declarations: tuple[InsertZoneDeclaration, ...] = (),
    zone_registry: dict | None = None,
) -> tuple[str, str] | None:
    """Return a rendered diff tuple when live rendering differs from current file."""
    outcome = render_insertions_file(
        target,
        registry,
        file_path=rel_path,
        zone_declarations=zone_declarations,
        zone_registry=zone_registry,
    )
    if outcome is None or not outcome.changed:
        return None
    return (
        rel_path,
        build_unified_diff(rel_path, outcome.original, outcome.result.text),
    )
