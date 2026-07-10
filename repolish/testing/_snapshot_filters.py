"""Composable filter helpers for snapshot test output."""

from __future__ import annotations

import re
from re import Pattern


def include_paths(  # noqa: PLR0913 - allowing several options
    rendered: dict[str, str],
    *,
    exact: set[str] | None = None,
    prefixes: tuple[str, ...] = (),
    exclude_prefixes: tuple[str, ...] = (),
    include_regex: tuple[str, ...] = (),
    exclude_regex: tuple[str, ...] = (),
) -> dict[str, str]:
    r"""Filter rendered output to include only paths matching the criteria.

    This helper is useful for snapshot tests where you want to assert on
    a subset of rendered files, or exclude mode-specific generated paths.

    All inclusion criteria are OR'd together: a path is included if it
    matches ``exact``, any ``prefixes``, or any ``include_regex``.
    Exclusion criteria are applied after inclusion and remove matching
    paths regardless of inclusion matches.

    Example::

        filtered = include_paths(
            rendered,
            exact={'poe_tasks.toml', 'README.md'},
            prefixes=('poe-tasks/', 'config/'),
            exclude_prefixes=('poe-tasks/sessions/',),
            include_regex=(r'.*\.jinja$',),
        )

    Args:
        rendered: The ``{dest_path: content}`` dict from
            :meth:`ProviderTestBed.render_all`.
        exact: Exact path matches to include.
        prefixes: Path prefixes to include (checked with ``startswith``).
        exclude_prefixes: Path prefixes to exclude (applied after inclusion).
        include_regex: Regex patterns to include. A path matching any
            pattern is included. Patterns are matched against the full path.
        exclude_regex: Regex patterns to exclude. A path matching any
            pattern is excluded, even if it matched an inclusion criterion.

    Returns:
        A filtered ``{dest_path: content}`` dict containing only paths
        that pass the inclusion/exclusion criteria.
    """
    # Compile regex patterns once
    include_patterns: tuple[Pattern[str], ...] = tuple(re.compile(p) for p in include_regex)
    exclude_patterns: tuple[Pattern[str], ...] = tuple(re.compile(p) for p in exclude_regex)

    result: dict[str, str] = {}

    for path, content in rendered.items():
        # Check exclusion first - these always win
        if _matches_prefixes(path, exclude_prefixes) or _matches_any_regex(
            path,
            exclude_patterns,
        ):
            continue

        # Check inclusion - at least one criterion must match
        if not _is_included(path, exact, prefixes, include_patterns):
            continue

        result[path] = content

    return result


def _matches_prefixes(path: str, prefixes: tuple[str, ...]) -> bool:
    """Check if path starts with any of the given prefixes."""
    return any(path.startswith(prefix) for prefix in prefixes)


def _matches_any_regex(path: str, patterns: tuple[Pattern[str], ...]) -> bool:
    """Check if path matches any of the compiled regex patterns."""
    return any(pattern.search(path) for pattern in patterns)


def _is_included(
    path: str,
    exact: set[str] | None,
    prefixes: tuple[str, ...],
    include_patterns: tuple[Pattern[str], ...],
) -> bool:
    """Check if path matches at least one inclusion criterion."""
    exact_match: bool = exact is not None and path in exact
    if exact_match:
        return True
    prefix_match: bool = bool(prefixes) and _matches_prefixes(path, prefixes)
    if prefix_match:
        return True
    regex_match: bool = bool(include_patterns) and _matches_any_regex(
        path,
        include_patterns,
    )
    return regex_match


def exclude_paths(
    rendered: dict[str, str],
    *,
    exact: set[str] | None = None,
    prefixes: tuple[str, ...] = (),
    regex: tuple[str, ...] = (),
) -> dict[str, str]:
    r"""Filter rendered output to exclude paths matching the criteria.

    This is the inverse of :func:`include_paths` - it removes paths that
    match the given criteria and keeps everything else.

    Example::

        filtered = exclude_paths(
            rendered,
            prefixes=('poe-tasks/sessions/', '.git/'),
            regex=(r'.*\.tmp$',),
        )

    Args:
        rendered: The ``{dest_path: content}`` dict from
            :meth:`ProviderTestBed.render_all`.
        exact: Exact path matches to exclude.
        prefixes: Path prefixes to exclude.
        regex: Regex patterns to exclude. Patterns are matched against
            the full path.

    Returns:
        A filtered ``{dest_path: content}`` dict with matching paths removed.
    """
    exclude_patterns: tuple[Pattern[str], ...] = tuple(re.compile(p) for p in regex)
    result: dict[str, str] = {}

    for path, content in rendered.items():
        if exact is not None and path in exact:
            continue
        if prefixes and path.startswith(prefixes):
            continue
        if regex and _matches_any_regex(path, exclude_patterns):
            continue
        result[path] = content

    return result
