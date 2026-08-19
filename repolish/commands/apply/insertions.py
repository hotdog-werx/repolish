"""Apply insertion registries to non-owned files after file writes."""

from __future__ import annotations

import difflib
import json
import traceback
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from hotlog import get_logger

from repolish.commands.apply.options import InsertionFileResult
from repolish.insertions import write_back
from repolish.insertions.parser import InsertionBlock, parse_text

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from repolish.insertions.writer import WriteBackResult
    from repolish.providers import SessionBundle

logger = get_logger(__name__)


@dataclass
class _ProviderInsertionContext:
    """State object for tracking insertion processing across providers."""

    rel_path: str
    registry: dict
    base_dir: Path
    provider_ids: list[str]
    pid_to_alias: dict[str, str] | None
    reports_dir: Path

    results: dict[str, InsertionFileResult] = field(default_factory=dict)
    provider_results: dict[str, dict[str, InsertionFileResult]] = field(
        default_factory=dict,
    )


@dataclass
class _StagedCheckResult:
    """Result of staged check-mode comparison for one file."""

    handled: bool
    diff: tuple[str, str] | None = None


@dataclass(frozen=True)
class _DisabledInsertionEntry:
    """One insertion block that was intentionally disabled by overrides."""

    tag: str
    function: str
    message: str


def _classify_block_for_provider(
    block_func: str,
    provider_alias: str,
    *,
    is_first_provider: bool = False,
) -> bool:
    """Check if a block function belongs to a specific provider.

    A block belongs to a provider if:
    - It's provider-qualified with this provider's alias (e.g., 'alpha:display-year')
    - It's unqualified and this provider is the first one (owns the fallback)

    For unqualified functions, the first provider owns ALL unqualified blocks,
    even if the function isn't registered (the failure is still that provider's).

    Args:
        block_func: The function name from the insertion block
        provider_alias: The provider's alias (e.g., 'alpha')
        provider_id: The provider's ID (filesystem path)
        registry: The full insertion registry
        is_first_provider: Whether this is the first provider for this file
    """
    if ':' in block_func:
        return block_func.startswith(f'{provider_alias}:')
    # Unqualified function - belongs to first provider only
    # Include ALL unqualified blocks for the first provider, even missing functions
    # (the failure is still that provider's responsibility)
    return bool(is_first_provider)


def _get_blocks_for_provider(
    text: str,
    provider_alias: str,
    *,
    is_first_provider: bool = False,
) -> list[InsertionBlock]:
    """Get insertion blocks that belong to a specific provider."""
    parsed = parse_text(text)
    return [
        b
        for b in parsed.blocks
        if _classify_block_for_provider(
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
        if _classify_block_for_provider(
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
        if _classify_block_for_provider(
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
    disabled_entries: list[_DisabledInsertionEntry],
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
            is_first_provider=is_first_provider,
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
            if _classify_block_for_provider(
                entry.function,
                provider_alias,
                is_first_provider=is_first_provider,
            )
        ]

        report_file = ctx.reports_dir / f'insertions.{_report_slug(ctx.rel_path)}.{provider_alias}.json'
        report_file.write_text(
            json.dumps(
                {
                    'file': ctx.rel_path,
                    'source_provider': provider_id,
                    'provider_alias': provider_alias,
                    'total_blocks': len(provider_blocks),
                    'failed_blocks': provider_failed,
                    'disabled_blocks': len(provider_disabled),
                    'functions': provider_functions,
                    'diagnostics': [
                        *[_diagnostic_report_entry(diag) for diag in provider_diagnostics],
                        *[_disabled_report_entry(entry) for entry in provider_disabled],
                    ],
                },
                indent=2,
            ),
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


def _diagnostic_report_entry(diag: object) -> dict[str, str | list[str] | None]:
    """Build a JSON-safe diagnostics payload including traceback when available."""
    exception = getattr(diag, 'exception', None)
    trace_lines = None
    if exception is not None:
        trace_text = ''.join(
            traceback.format_exception(
                type(exception),
                exception,
                exception.__traceback__,
            ),
        )
        trace_lines = trace_text.splitlines()
    return {
        'kind': 'error',
        'tag': getattr(diag, 'tag', '<unknown>'),
        'message': getattr(diag, 'message', ''),
        'traceback': trace_lines,
    }


def _disabled_report_entry(
    entry: _DisabledInsertionEntry,
) -> dict[str, str | list[str] | None]:
    """Build a report diagnostics payload for a block disabled by config overrides."""
    return {
        'kind': 'disabled',
        'tag': entry.tag,
        'function': entry.function,
        'message': entry.message,
        'traceback': None,
    }


def _resolve_renderer_for_function(
    registry: dict,
    function_name: str,
) -> Callable[[InsertionBlock], str] | None:
    """Resolve a renderer the same way insertion writing resolves function lookups."""
    renderer = registry.get(function_name)
    if renderer is None and ':' in function_name:
        renderer = registry.get(function_name.rsplit(':', 1)[1])
    return renderer


def _disabled_reason_for_block(
    block: InsertionBlock,
    registry: dict,
) -> str | None:
    """Return a human-readable disable reason for one block, when configured."""
    renderer = _resolve_renderer_for_function(registry, block.function)
    if renderer is None:
        return None

    disabled_tags = getattr(renderer, '__repolish_disabled_tags__', frozenset())
    if block.tag in disabled_tags:
        return f'Insertion block disabled by tag override: tag={block.tag!r}, function={block.function!r}.'

    disabled_functions = getattr(
        renderer,
        '__repolish_disabled_functions__',
        frozenset(),
    )
    if disabled_functions:
        return f'Insertion block disabled by function override: tag={block.tag!r}, function={block.function!r}.'
    return None


def _collect_disabled_entries(
    blocks: list[InsertionBlock],
    registry: dict,
) -> list[_DisabledInsertionEntry]:
    """Collect disabled insertion metadata for summary/report output."""
    entries: list[_DisabledInsertionEntry] = []
    for block in blocks:
        reason = _disabled_reason_for_block(block, registry)
        if reason is not None:
            entries.append(
                _DisabledInsertionEntry(
                    tag=block.tag,
                    function=block.function,
                    message=reason,
                ),
            )
    return entries


def _apply_file_insertions(
    ctx: _ProviderInsertionContext,
) -> tuple[InsertionFileResult, dict[str, dict[str, InsertionFileResult]]]:
    """Apply insertions for a single file and return results."""
    target = ctx.base_dir / ctx.rel_path
    original_text = target.read_text(encoding='utf-8')
    parsed = parse_text(original_text)
    disabled_entries = _collect_disabled_entries(parsed.blocks, ctx.registry)
    result = write_back(original_text, ctx.registry)
    target.write_text(result.text, encoding='utf-8')

    if result.total_blocks == 0:
        return (
            InsertionFileResult(
                total_blocks=0,
                failed_blocks=0,
                functions=(),
                diagnostics=(),
            ),
            {ctx.rel_path: {}},
        )

    tag_to_func = _build_tag_to_func_map(parsed.blocks)
    aggregated, per_provider = _process_provider_insertions(
        ctx,
        original_text,
        result,
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
    if paused_files and rel_path in paused_files:
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


def apply_registered_insertions(
    providers: SessionBundle,
    base_dir: Path,
    pid_to_alias: dict[str, str] | None = None,
) -> tuple[
    dict[str, InsertionFileResult],
    dict[str, dict[str, InsertionFileResult]],
]:
    """Render provider-registered insertion blocks into target files in-place.

    When multiple providers target the same file, each provider's insertions
    are tracked separately for reporting. Reports are written per-provider.
    """
    results: dict[str, InsertionFileResult] = {}
    provider_results: dict[str, dict[str, InsertionFileResult]] = {}
    reports_dir = base_dir / '.repolish' / '_' / 'insertions'
    reports_dir.mkdir(parents=True, exist_ok=True)
    paused_files = providers.paused_files

    for rel_path, registry in providers.file_insertions.items():
        provider_ids = providers.insertion_sources.get(rel_path, [])
        if not _should_skip_file(rel_path, base_dir, paused_files):
            ctx = _ProviderInsertionContext(
                rel_path=rel_path,
                registry=registry,
                base_dir=base_dir,
                provider_ids=provider_ids,
                pid_to_alias=pid_to_alias,
                reports_dir=reports_dir,
            )

            aggregated, file_provider_results = _apply_file_insertions(ctx)
            results[rel_path] = aggregated
            _merge_provider_results(
                provider_results,
                rel_path,
                file_provider_results[ctx.rel_path],
            )

    return results, provider_results


def _report_slug(path: str) -> str:
    """Convert a destination path to a stable report filename slug."""
    return path.replace('/', '--')


def stage_registered_insertions(
    providers: SessionBundle,
    base_dir: Path,
    setup_output: Path,
) -> None:
    """Render insertion targets into staged output for apply/check parity.

    For files that already exist in the staged tree, render insertions on top of
    staged content. Otherwise render from the developer-owned file in ``base_dir``
    and materialize the result in staged output.
    """
    staged_root = setup_output / 'repolish'
    paused_files = providers.paused_files

    for rel_path, registry in providers.file_insertions.items():
        target = base_dir / rel_path
        if _should_skip_file(rel_path, base_dir, paused_files):
            continue

        staged_file = staged_root / rel_path
        source_text = (
            staged_file.read_text(encoding='utf-8')
            if staged_file.exists() and staged_file.is_file()
            else target.read_text(encoding='utf-8')
        )

        rendered = write_back(source_text, registry).text
        staged_file.parent.mkdir(parents=True, exist_ok=True)
        staged_file.write_text(rendered, encoding='utf-8')


def check_registered_insertions(
    providers: SessionBundle,
    base_dir: Path,
    setup_output: Path | None = None,
) -> list[tuple[str, str]]:
    """Return insertion drift diffs for check mode without mutating files."""
    diffs: list[tuple[str, str]] = []
    paused_files = providers.paused_files

    for rel_path, registry in providers.file_insertions.items():
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
    if not staged_file.exists() or not staged_file.is_file():
        return _StagedCheckResult(handled=False)

    current = target.read_text(encoding='utf-8')
    rendered = staged_file.read_text(encoding='utf-8')
    if current == rendered:
        return _StagedCheckResult(handled=True)
    return _StagedCheckResult(
        handled=True,
        diff=(rel_path, _build_unified_diff(rel_path, current, rendered)),
    )


def _rendered_diff_if_any(
    *,
    rel_path: str,
    target: Path,
    registry: dict,
) -> tuple[str, str] | None:
    """Return a rendered diff tuple when live rendering differs from current file."""
    current = target.read_text(encoding='utf-8')
    rendered = write_back(current, registry).text
    if current == rendered:
        return None
    return (rel_path, _build_unified_diff(rel_path, current, rendered))


def _build_unified_diff(
    rel_path: str,
    current: str,
    rendered: str,
) -> str:
    """Build a unified diff between current and rendered text."""
    return ''.join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            rendered.splitlines(keepends=True),
            fromfile=rel_path,
            tofile=rel_path,
        ),
    )
