import fnmatch
import shutil
from pathlib import Path


def create_cookiecutter_template(
    staging_dir: Path,
    template_directories: list[Path] | list[tuple[str | None, Path]],
    *,
    template_overrides: dict[str, str] | None = None,
) -> Path:
    """Create a cookiecutter template in a staging directory.

    This function merges a sequence of provider template directories into a
    single staging template. If the same file exists in multiple directories,
    the later entry wins (i.e. last provider overrides earlier ones).

    When ``template_overrides`` is provided the merging behaviour is altered
    on a per-file basis. The mapping keys are shell-style glob patterns
    (matching the relative POSIX path within the template), and values are
    provider aliases. When a file path matches a pattern and the associated
    alias does **not** match the alias of the current directory being processed
    the file is skipped, preventing later providers from overriding the
    specified source.

    Args:
        staging_dir: Path to the staging directory to create the templates.
        template_directories: Sequence of either Path objects or
            ``(alias, Path)`` tuples.  When a tuple is provided the alias is
            used to evaluate ``template_overrides``; plain Path entries ignore
            any overrides.
        template_overrides: Optional mapping of glob patterns to provider
            aliases controlling per-file override behaviour.

    Returns:
        The Path to the staging directory containing the combined templates.
    """
    # normalize incoming list to pairs (alias may be None)
    entries: list[tuple[str | None, Path]] = []
    for entry in template_directories:
        if isinstance(entry, tuple):
            alias, path = entry
            entries.append((alias, path))
        else:
            entries.append((None, entry))

    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    for alias, template_dir in entries:
        _copy_template_dir(
            template_dir,
            staging_dir,
            alias=alias,
            overrides=template_overrides,
        )
    return staging_dir


def _selected_override_alias(
    rel_path: str,
    overrides: dict[str, str] | None,
) -> str | None:
    """Return the alias selected by ``overrides`` for ``rel_path``.

    The last matching pattern wins (consistent with previous behaviour).
    """
    if not overrides:
        return None
    selected: str | None = None
    for pat, ali in overrides.items():
        if fnmatch.fnmatch(rel_path, pat):
            selected = ali
    return selected


def _copy_item_to_dest(item: Path, repolish_dir: Path, dest_root: Path) -> None:
    """Copy a single filesystem entry from ``repolish_dir`` to ``dest_root``.

    Handles directory creation and strips a trailing ``.jinja`` suffix from
    destination filenames.
    """
    rel = item.relative_to(repolish_dir)
    if rel.suffix == '.jinja':
        rel = rel.with_suffix('')
    dest = dest_root / rel
    if item.is_dir():
        dest.mkdir(parents=True, exist_ok=True)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest)


def _copy_template_dir(
    template_dir: Path,
    staging_dir: Path,
    *,
    alias: str | None = None,
    overrides: dict[str, str] | None = None,
) -> None:
    """Copy the contents of a template directory into the staging directory.

    Each provider is expected to have a `repolish/` subdirectory containing
    the project layout files. These will be copied over to the staging dir under
    the special folder `{{cookiecutter._repolish_project}}`.

    When ``overrides`` is provided and ``alias`` is not None, files whose
    relative path matches a pattern in the overrides mapping *and* whose
    override alias differs from ``alias`` will be skipped.  This prevents later
    providers from overwriting a file that has been pinned to an earlier
    provider.
    """
    repolish_dir = template_dir / 'repolish'
    if not (repolish_dir.exists() and repolish_dir.is_dir()):
        return

    dest_root = staging_dir / '{{cookiecutter._repolish_project}}'
    for item in repolish_dir.rglob('*'):
        rel = item.relative_to(repolish_dir)
        rel_str = rel.as_posix()

        # respect overrides if configured and alias provided
        if alias is not None:
            selected = _selected_override_alias(rel_str, overrides)
            if selected is not None and selected != alias:
                continue

        _copy_item_to_dest(item, repolish_dir, dest_root)
