from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path

from rich.tree import Tree

from repolish.commands.apply import ApplyOptions, resolve_session
from repolish.console import console


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


def _provider_function_name(
    key: str,
    provider_alias: str,
    *,
    is_first_provider: bool,
) -> str | None:
    """Resolve registry key ownership to one provider-visible function name."""
    if key.startswith(f'{provider_alias}:'):
        return key.split(':', 1)[1]
    if ':' in key:
        return None
    return key if is_first_provider else None


def _doc_parts(fn: object) -> tuple[str, str]:
    """Return (summary, full_doc) for a callable."""
    doc = inspect.getdoc(fn) or ''
    if not doc:
        return 'No docstring provided.', ''
    lines = [line for line in doc.splitlines() if line.strip()]
    summary = lines[0] if lines else 'No docstring provided.'
    return summary, doc


def _build_index(options: ListInsertionsOptions) -> list[_InsertionFunctionInfo]:
    """Collect insertion function metadata from a resolved session."""
    session = resolve_session(ApplyOptions(config_path=options.config_path))
    by_key: dict[tuple[str, str], _InsertionFunctionInfo] = {}

    for file_path, provider_ids in session.providers.insertion_sources.items():
        registry = session.providers.file_insertions.get(file_path, {})
        for idx, provider_id in enumerate(provider_ids):
            provider_alias = session.pid_to_alias.get(provider_id, provider_id)
            for key, fn in registry.items():
                function_name = _provider_function_name(
                    key,
                    provider_alias,
                    is_first_provider=idx == 0,
                )
                if function_name is None:
                    continue
                if options.provider and provider_alias != options.provider:
                    continue
                if options.function and function_name != options.function:
                    continue

                cache_key = (provider_alias, function_name)
                if cache_key not in by_key:
                    summary, doc = _doc_parts(fn)
                    by_key[cache_key] = _InsertionFunctionInfo(
                        provider_alias=provider_alias,
                        function_name=function_name,
                        summary=summary,
                        doc=doc,
                    )
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
