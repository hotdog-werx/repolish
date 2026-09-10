from pathlib import Path

from hotlog import get_logger

from repolish.config import ProviderSymlink, ResolvedProviderInfo
from repolish.config.models.provider import ProviderCopy
from repolish.config.paused import is_paused
from repolish.linker.orchestrator import (
    create_provider_copies,
    create_provider_symlinks,
)
from repolish.linker.windows_utils import normalize_windows_path

logger = get_logger(__name__)


def check_symlinks(
    resolved_symlinks: dict[str, list[ProviderSymlink]],
    providers: dict[str, ResolvedProviderInfo],
) -> list[str]:
    """Validate all expected symlinks and return a list of issue strings.

    Each issue string identifies the provider alias and describes the problem
    (missing symlink, wrong target, or path exists but is not a symlink).
    Returns an empty list when every symlink is present and correct.
    """
    issues: list[str] = []
    for alias, symlinks in resolved_symlinks.items():
        info = providers.get(alias)
        if info is None:  # pragma: no cover
            continue
        for symlink in symlinks:
            source_path = (info.resources_dir / symlink.source).resolve()
            issue = _check_one_symlink(alias, symlink, source_path)
            if issue is not None:
                issues.append(issue)
    return issues


def _check_one_symlink(
    alias: str,
    symlink: ProviderSymlink,
    source_path: Path,
) -> str | None:
    """Return an issue string if the symlink is wrong/missing, else None."""
    target_path = Path(symlink.target)
    if target_path.is_symlink():
        actual = normalize_windows_path(target_path.readlink().resolve())
        source_path = normalize_windows_path(source_path)
        if actual != source_path:
            return f'{alias}: symlink {symlink.target!s} → {actual!s} (expected → {source_path!s})'
        return None
    if target_path.exists():
        return f'{alias}: {symlink.target!s} exists but is not a symlink'
    return f'{alias}: missing symlink {symlink.target!s} → {symlink.source!s}'


def apply_symlinks(
    resolved_symlinks: dict[str, list[ProviderSymlink]],
    providers: dict[str, ResolvedProviderInfo],
) -> None:
    """Materialise all resolved symlinks for every provider.

    Delegates to `create_provider_symlinks` for each alias that appears in
    both `resolved_symlinks` and `providers`. Providers absent from the
    current config are silently skipped.
    """
    for alias, symlinks in resolved_symlinks.items():
        info = providers.get(alias)
        if info:
            create_provider_symlinks(alias, info.resources_dir, symlinks)


def _disabled_copy_targets(info: ResolvedProviderInfo) -> frozenset[str]:
    """Return copy targets disabled via ``overrides.copies`` for *info*'s provider.

    Disabled targets are files the project owns outright; repolish drops
    them silently (the config entry is the user's own record of the decision).
    """
    overrides = info.overrides
    if overrides is None or not overrides.copies:
        return frozenset()
    return frozenset(target for target, enabled in overrides.copies.items() if not enabled)


def apply_copies(
    resolved_copies: dict[str, list[ProviderCopy]],
    providers: dict[str, ResolvedProviderInfo],
    *,
    paused_files: frozenset[str] = frozenset(),
) -> None:
    """Materialise all resolved resource copies for every provider.

    Delegates to `create_provider_copies` for each alias that appears in
    both `resolved_copies` and `providers`. Providers absent from the
    current config are silently skipped.

    Copy targets listed in `paused_files` are skipped: unlike symlinks,
    copies are committed project files, so pausing one must stop repolish
    from re-copying the provider version over local fixes. Targets disabled
    via `overrides.copies` (project-owned files) are dropped silently. For
    directory copies both sets are forwarded so `create_provider_copies` can
    also skip individual files *inside* the copied tree.
    """
    for alias, copies in resolved_copies.items():
        info = providers.get(alias)
        if not info:
            continue
        disabled_copies = _disabled_copy_targets(info)
        active_copies = []
        for copy in copies:
            if is_paused(copy.target.as_posix(), paused_files):
                logger.info(
                    'copy_paused',
                    provider=alias,
                    target=str(copy.target),
                    suggestion='remove the entry from paused_files once the local fix is no longer needed',
                    _display_level=1,
                )
                continue
            active_copies.append(copy)
        create_provider_copies(
            alias,
            info.resources_dir,
            active_copies,
            paused_files=paused_files,
            disabled_copies=disabled_copies,
        )
