"""Derivation for the insertion catalog: registries in, rows out.

`repolish list-insertions` hands a resolved session to
`insertion_function_rows` and gets one group per provider with one row
per insertion function, each carrying the docstring summary and the
files whose developer markers may call it. Rendering lives in
`repolish.reporting.leaves`.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from repolish.insertions import resolve_provider_function_name
from repolish.summaries.rows import InsertionCatalogGroup, InsertionFunctionRow

if TYPE_CHECKING:
    from repolish.summaries.contract import InsertionCatalogSession


@dataclass
class _InsertionFunctionInfo:
    """Indexed insertion function metadata for grouping."""

    provider_alias: str
    function_name: str
    summary: str
    files: set[str] = field(default_factory=set)


def _function_summary(fn: object) -> str:
    """Return the first docstring line of a callable, or a placeholder."""
    doc = inspect.getdoc(fn) or ''
    lines = [line for line in doc.splitlines() if line.strip()]
    return lines[0] if lines else 'No docstring provided.'


def _resolve_function_entry(  # noqa: PLR0913 - may need refactoring
    key: str,
    fn: object,
    provider_alias: str,
    *,
    is_first_provider: bool,
    provider: str | None,
    function: str | None,
) -> _InsertionFunctionInfo | None:
    """Resolve a registry entry to _InsertionFunctionInfo or None if filtered."""
    function_name = resolve_provider_function_name(
        key,
        provider_alias,
        is_first_provider=is_first_provider,
    )
    if function_name is None or (provider and provider_alias != provider) or (function and function_name != function):
        return None

    return _InsertionFunctionInfo(
        provider_alias=provider_alias,
        function_name=function_name,
        summary=_function_summary(fn),
    )


def _index_provider_registry(
    registry: dict,
    provider_alias: str,
    *,
    is_first_provider: bool,
    provider: str | None,
    function: str | None,
) -> dict[tuple[str, str], _InsertionFunctionInfo]:
    """Build an index of insertion functions from a single provider's registry.

    Args:
        registry: The provider's insertion function registry
        provider_alias: The provider's alias
        is_first_provider: Whether this is the first provider for the file
        provider: Alias filter, or None to list every provider
        function: Function-name filter, or None to list every function

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
            provider=provider,
            function=function,
        ):
            cache_key = (result.provider_alias, result.function_name)
            by_key[cache_key] = result
    return by_key


def _merge_indexed(
    by_key: dict[tuple[str, str], _InsertionFunctionInfo],
    indexed: dict[tuple[str, str], _InsertionFunctionInfo],
    file_path: str,
) -> None:
    """Merge one provider's index into the session-wide one, recording the file."""
    for cache_key, info in indexed.items():
        if cache_key not in by_key:
            by_key[cache_key] = info
        by_key[cache_key].files.add(file_path)


def _index_session(
    session: InsertionCatalogSession,
    *,
    provider: str | None,
    function: str | None,
) -> dict[tuple[str, str], _InsertionFunctionInfo]:
    """Index every insertion function across every file's providers."""
    by_key: dict[tuple[str, str], _InsertionFunctionInfo] = {}
    for file_path, provider_ids in session.providers.insertion_sources.items():
        registry = session.providers.file_insertions.get(file_path, {})
        for idx, provider_id in enumerate(provider_ids):
            provider_alias = session.pid_to_alias.get(provider_id, provider_id)
            indexed = _index_provider_registry(
                registry,
                provider_alias,
                is_first_provider=idx == 0,
                provider=provider,
                function=function,
            )
            _merge_indexed(by_key, indexed, file_path)
    return by_key


def _catalog_groups(
    by_key: dict[tuple[str, str], _InsertionFunctionInfo],
) -> list[InsertionCatalogGroup]:
    """Group the index into one sorted InsertionCatalogGroup per provider."""
    by_provider: dict[str, list[InsertionFunctionRow]] = {}
    for info in sorted(
        by_key.values(),
        key=lambda i: (i.provider_alias, i.function_name),
    ):
        by_provider.setdefault(info.provider_alias, []).append(
            InsertionFunctionRow(
                name=info.function_name,
                summary=info.summary,
                files=tuple(sorted(info.files)),
            ),
        )
    return [InsertionCatalogGroup(provider=alias, functions=tuple(rows)) for alias, rows in by_provider.items()]


def insertion_function_rows(
    session: InsertionCatalogSession,
    *,
    provider: str | None = None,
    function: str | None = None,
) -> list[InsertionCatalogGroup]:
    """Build one group per provider that exposes insertion functions.

    The same function registered for one provider across several files
    contributes a single row listing every file. Groups and rows are
    sorted by name, and only providers whose functions survive the
    filters appear.
    """
    by_key = _index_session(session, provider=provider, function=function)
    return _catalog_groups(by_key)
