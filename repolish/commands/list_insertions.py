from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rich.tree import Tree

from repolish.commands.apply import ApplyOptions, resolve_session
from repolish.console import console
from repolish.insertions import resolve_provider_function_name

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class ListInsertionsOptions:
    """Options for listing available insertion functions."""

    config_path: Path
    provider: str | None = None
    function: str | None = None


@dataclass
class _InsertionFunctionInfo:
    """Indexed insertion function metadata for display."""

    provider_alias: str
    function_name: str
    summary: str
    doc: str
    files: set[str] = field(default_factory=set)


def _doc_parts(fn: object) -> tuple[str, str]:
    """Return (summary, full_doc) for a callable."""
    doc = inspect.getdoc(fn) or ''
    if not doc:
        return 'No docstring provided.', ''
    lines = [line for line in doc.splitlines() if line.strip()]
    summary = lines[0] if lines else 'No docstring provided.'
    return summary, doc


def _resolve_function_entry(
    key: str,
    fn: object,
    provider_alias: str,
    *,
    is_first_provider: bool,
    options: ListInsertionsOptions,
) -> _InsertionFunctionInfo | None:
    """Resolve a registry entry to _InsertionFunctionInfo or None if filtered."""
    function_name = resolve_provider_function_name(
        key,
        provider_alias,
        is_first_provider=is_first_provider,
    )
    if function_name is None:
        return None
    if options.provider and provider_alias != options.provider:
        return None
    if options.function and function_name != options.function:
        return None

    summary, doc = _doc_parts(fn)
    return _InsertionFunctionInfo(
        provider_alias=provider_alias,
        function_name=function_name,
        summary=summary,
        doc=doc,
    )


def _index_provider_registry(
    registry: dict,
    provider_alias: str,
    *,
    is_first_provider: bool,
    options: ListInsertionsOptions,
) -> dict[tuple[str, str], _InsertionFunctionInfo]:
    """Build an index of insertion functions from a single provider's registry.

    Args:
        registry: The provider's insertion function registry
        provider_alias: The provider's alias
        is_first_provider: Whether this is the first provider for the file
        options: Filter options

    Returns:
        Dict mapping (provider_alias, function_name) to _InsertionFunctionInfo
    """
    by_key: dict[tuple[str, str], _InsertionFunctionInfo] = {}
    for key, fn in registry.items():
        if result := _resolve_function_entry(
            key,
            fn,
            provider_alias,
            is_first_provider=is_first_provider,
            options=options,
        ):
            cache_key = (result.provider_alias, result.function_name)
            by_key[cache_key] = result
    return by_key


def _build_index(
    options: ListInsertionsOptions,
) -> list[_InsertionFunctionInfo]:
    """Collect insertion function metadata from a resolved session."""
    session = resolve_session(ApplyOptions(config_path=options.config_path))
    by_key: dict[tuple[str, str], _InsertionFunctionInfo] = {}

    for file_path, provider_ids in session.providers.insertion_sources.items():
        registry = session.providers.file_insertions.get(file_path, {})
        for idx, provider_id in enumerate(provider_ids):
            provider_alias = session.pid_to_alias.get(provider_id, provider_id)
            provider_index = _index_provider_registry(
                registry,
                provider_alias,
                is_first_provider=idx == 0,
                options=options,
            )
            for cache_key, info in provider_index.items():
                if cache_key not in by_key:
                    by_key[cache_key] = info
                by_key[cache_key].files.add(file_path)

    return sorted(
        by_key.values(),
        key=lambda info: (info.provider_alias, info.function_name),
    )


def _print_index(index: list[_InsertionFunctionInfo]) -> None:
    """Render insertion function index as a tree."""
    if not index:
        console.print('No insertion functions found for the requested filters.')
        return

    provider_names = {entry.provider_alias for entry in index}
    root = Tree(
        f'[bold]available insertion functions[/bold] ({len(provider_names)} providers, {len(index)} functions)',
    )

    by_provider: dict[str, list[_InsertionFunctionInfo]] = {}
    for entry in index:
        by_provider.setdefault(entry.provider_alias, []).append(entry)

    for provider_alias in sorted(by_provider):
        entries = by_provider[provider_alias]
        provider_branch = root.add(
            f'[bold]{provider_alias}[/bold] ({len(entries)} functions)',
        )
        for entry in entries:
            files = ', '.join(sorted(entry.files))
            fn_branch = provider_branch.add(
                f'{entry.function_name}  [dim]- {entry.summary}[/dim]',
            )
            fn_branch.add(f'[dim]files:[/dim] {files}')

    console.print(root)


def command(options: ListInsertionsOptions) -> int:
    """List insertion functions available from configured providers."""
    index = _build_index(options)
    _print_index(index)
    return 0
