from pathlib import Path

from repolish.config import ProviderSymlink, ResolvedProviderInfo
from repolish.linker.orchestrator import create_provider_symlinks
from repolish.linker.windows_utils import normalize_windows_path


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
