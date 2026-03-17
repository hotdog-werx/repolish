import fnmatch
import shutil
from pathlib import Path


def stage_templates(
    staging_dir: Path,
    # `list` is invariant, so a union of two list types rejects callers that
    # supply `list[tuple[str, Path]]` even though that form is perfectly
    # valid.  using an element-level union lets mypy/ty treat the argument as
    # `list[Path | tuple[str | None, Path]]` which accepts both plain paths and
    # (alias, path) pairs with or without a `None` alias.
    template_directories: list[Path | tuple[str | None, Path]],
    *,
    template_overrides: dict[str, str] | None = None,
    excluded_sources: set[str] | None = None,
) -> tuple[Path, dict[str, str]]:
    """Merge provider template directories into a single staging tree.

    Each provider contributes a `repolish/` subdirectory; files are merged in
    order so the last provider wins when the same path appears more than once.

    When `template_overrides` is provided the merging behaviour is altered
    on a per-file basis. The mapping keys are shell-style glob patterns
    (matching the relative POSIX path within the template), and values are
    provider aliases. When a file path matches a pattern and the associated
    alias does **not** match the alias of the current directory being processed
    the file is skipped, preventing later providers from overriding the
    specified source.

    When `excluded_sources` is provided, any file whose path (relative to the
    provider's ``repolish/`` directory, with ``.jinja`` stripped) appears in
    the set is skipped.  This prevents a template that a provider has
    explicitly placed in ``create_file_mappings`` from also being auto-copied
    to its natural staging position.

    Args:
        staging_dir: Path to the staging directory to create the templates.
        template_directories: Sequence of either Path objects or
            `(alias, Path)` tuples.  When a tuple is provided the alias is
            used to evaluate `template_overrides`; plain Path entries ignore
            any overrides.
        template_overrides: Optional mapping of glob patterns to provider
            aliases controlling per-file override behaviour.
        excluded_sources: Optional set of POSIX source-template paths (without
            the ``.jinja`` suffix) that should be excluded from auto-staging.

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

    # we'll record which provider supplied each file (relative path -> pid)
    sources: dict[str, str] = {}

    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    for alias, template_dir in entries:
        _copy_template_dir(
            template_dir,
            staging_dir,
            alias=alias,
            overrides=template_overrides,
            excluded_sources=excluded_sources,
            sources=sources,
        )
    return staging_dir, sources


def _selected_override_alias(
    rel_path: str,
    overrides: dict[str, str] | None,
) -> str | None:
    """Return the alias selected by `overrides` for `rel_path`.

    The last matching pattern wins (consistent with previous behaviour).
    """
    if not overrides:
        return None
    selected: str | None = None
    for pat, ali in overrides.items():
        if fnmatch.fnmatch(rel_path, pat):
            selected = ali
    return selected


def _copy_item_to_dest(
    item: Path,
    repolish_dir: Path,
    dest_root: Path,
    *,
    alias: str | None,
    sources: dict[str, str] | None,
) -> None:
    """Copy a single filesystem entry from `repolish_dir` to `dest_root`.

    Handles directory creation and strips a trailing `.jinja` suffix from
    destination filenames.  When `sources` is not ``None``, also records the
    provider id for the final relative path in it; pass ``None`` to stage the
    file without registering it as an auto-staged template (used for files that
    are claimed by ``create_file_mappings``).
    """
    rel = item.relative_to(repolish_dir)
    if rel.suffix == '.jinja':
        rel = rel.with_suffix('')
    dest = dest_root / rel

    # record provider provenance using the post-stripped path
    pid = alias if alias is not None else str(repolish_dir.parent)
    # normalise provider id to POSIX style (forward slashes) so it matches the
    # value used by the loader, which calls `Path(directory).as_posix()`.
    # On Windows `str(Path)` returns backslashes, and some providers may
    # still supply literal backslashes in aliases.  converting here ensures
    # the string uses forward slashes regardless of platform.
    pid = pid.replace('\\', '/')
    pid = Path(pid).as_posix()
    if sources is not None:
        sources[rel.as_posix()] = pid

    if item.is_dir():
        dest.mkdir(parents=True, exist_ok=True)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest)


def _should_skip_item(
    _item: Path,
    rel_str: str,
    *,
    alias: str | None,
    overrides: dict[str, str] | None,
) -> bool:
    """Return True if *item* should be fully skipped during staging.

    A file is skipped when it is governed by ``overrides`` and the current
    provider's alias is not the selected one for that path.  Files that appear
    in ``excluded_sources`` are handled separately: they are still copied into
    the staging tree (so file_mappings can find them) but are not registered in
    ``sources``.
    """
    if alias is not None:
        selected = _selected_override_alias(rel_str, overrides)
        if selected is not None and selected != alias:
            return True
    return False


def _copy_template_dir(  # noqa: PLR0913
    template_dir: Path,
    staging_dir: Path,
    *,
    alias: str | None = None,
    overrides: dict[str, str] | None = None,
    excluded_sources: set[str] | None = None,
    sources: dict[str, str],
) -> None:
    """Copy the contents of a template directory into the staging directory.

    Each provider is expected to have a `repolish/` subdirectory containing
    the project layout files. These will be copied over to the staging dir under
    the staging directory root.

    Files are skipped when overrides pin them to a different provider alias,
    or when they appear in ``excluded_sources`` (explicitly mapped via
    ``create_file_mappings``).
    """
    repolish_dir = template_dir / 'repolish'
    if not (repolish_dir.exists() and repolish_dir.is_dir()):
        return

    dest_root = staging_dir / 'repolish'
    for item in repolish_dir.rglob('*'):
        rel_str = item.relative_to(repolish_dir).as_posix()
        # Override mismatch: a different provider owns this file — skip entirely.
        if _should_skip_item(item, rel_str, alias=alias, overrides=overrides):
            continue
        # Explicitly mapped source: stage the file so file_mappings can find it
        # in setup_output and register it in sources so the renderer can look up
        # the declaring provider's context (e.g. for {{ _provider }} access).
        # build_file_records filters these out so they don't appear as managed
        # output files.
        if excluded_sources is not None and item.is_file() and rel_str.removesuffix('.jinja') in excluded_sources:
            _copy_item_to_dest(
                item,
                repolish_dir,
                dest_root,
                alias=alias,
                sources=sources,
            )
            continue
        _copy_item_to_dest(
            item,
            repolish_dir,
            dest_root,
            alias=alias,
            sources=sources,
        )
