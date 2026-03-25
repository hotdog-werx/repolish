import fnmatch
import shutil
from pathlib import Path

from repolish.misc import is_conditional_file


def stage_templates(
    staging_dir: Path,
    # `list` is invariant, so a union of two list types rejects callers that
    # supply `list[tuple[str, Path]]` even though that form is perfectly
    # valid.  using an element-level union lets mypy/ty treat the argument as
    # `list[Path | tuple[str | None, Path]]` which accepts both plain paths and
    # (alias, path) pairs with or without a `None` alias.
    template_directories: list[Path | tuple[str | None, Path]],
    *,
    template_overrides: dict[str, str | None] | None = None,
    mapped_sources: set[str] | None = None,
    workspace_mode: str | None = None,
) -> tuple[Path, dict[str, str]]:
    """Merge provider template directories into a single staging tree.

    Each provider contributes a ``repolish/`` subdirectory; files are merged in
    order so the last provider wins when the same path appears more than once.

    When `workspace_mode` is provided (``'root'``, ``'member'``, or
    ``'standalone'``), each provider directory is also checked for a
    mode-specific sibling directory at ``provider_root/{workspace_mode}/``.
    When that directory exists, its files are staged *after* the provider's
    main ``repolish/`` templates so they take precedence for that mode.  Files
    that only belong in one mode live in the mode directory; files shared
    across all modes live in ``repolish/``.

    When `template_overrides` is provided the merging behaviour is altered
    on a per-file basis. The mapping keys are shell-style glob patterns
    (matching the relative POSIX path within the template), and values are
    provider aliases. When a file path matches a pattern and the associated
    alias does **not** match the alias of the current directory being processed
    the file is skipped, preventing later providers from overriding the
    specified source.

    When `mapped_sources` is provided, any ``_repolish.*`` file whose path
    (relative to the provider's ``repolish/`` directory, with ``.jinja``
    stripped) is *not* in the set is skipped.  This prevents unmapped
    conditional templates from appearing in the staging area — only sources
    explicitly referenced by ``create_file_mappings`` are staged.

    Args:
        staging_dir: Path to the staging directory to create the templates.
        template_directories: Sequence of either Path objects or
            `(alias, Path)` tuples.  When a tuple is provided the alias is
            used to evaluate `template_overrides`; plain Path entries ignore
            any overrides.
        template_overrides: Optional mapping of glob patterns to provider
            aliases (or ``None``) controlling per-file override behaviour.
            A ``None`` value suppresses the file entirely — it will not be
            staged or rendered in the output.
        mapped_sources: Optional set of POSIX source-template paths (without
            the ``.jinja`` suffix) that are claimed by ``create_file_mappings``.
            ``_repolish.*`` files whose stripped path is not in this set are
            skipped during staging.
        workspace_mode: Current workspace mode (``'root'``, ``'member'``, or
            ``'standalone'``).  When set, each provider's mode-specific overlay
            directory is staged after its base ``repolish/`` templates.

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
            mapped_sources=mapped_sources,
            sources=sources,
        )
        if workspace_mode:
            mode_dir = template_dir / workspace_mode
            if mode_dir.is_dir():
                _copy_mode_overlay_dir(
                    mode_dir,
                    staging_dir,
                    alias=alias,
                    mode_name=workspace_mode,
                    overrides=template_overrides,
                    mapped_sources=mapped_sources,
                    sources=sources,
                )
    return staging_dir, sources


_UNMATCHED: str | None = None  # sentinel — value never actually read when matched=False


def _selected_override_alias(
    rel_path: str,
    overrides: dict[str, str | None] | None,
) -> tuple[bool, str | None]:
    """Return ``(matched, alias)`` for `rel_path` against `overrides`.

    - ``(False, None)`` — no pattern matched; caller should not act on alias.
    - ``(True, str)``   — pattern matched; the file belongs to *alias*.
    - ``(True, None)``  — pattern matched with a ``None`` value; the file
      should be suppressed entirely (not staged or rendered).

    The last matching pattern wins (consistent with previous behaviour).
    """
    if not overrides:
        return False, _UNMATCHED
    matched = False
    selected: str | None = None
    for pat, ali in overrides.items():
        if fnmatch.fnmatch(rel_path, pat):
            matched = True
            selected = ali
    return matched, selected


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
    if item.is_dir():
        dest.mkdir(parents=True, exist_ok=True)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest)
        if sources is not None:
            sources[rel.as_posix()] = pid


def _should_skip_item(
    _item: Path,
    rel_str: str,
    *,
    alias: str | None,
    overrides: dict[str, str | None] | None,
) -> bool:
    """Return True if *item* should be fully skipped during staging.

    A file is skipped when:
    - a ``None`` override suppresses it entirely, or
    - a different provider's alias is selected for that path.

    Files that appear in ``mapped_sources`` are handled separately: they are
    still copied into the staging tree (so file_mappings can find them) but
    are not registered in ``sources``.
    """
    matched, selected = _selected_override_alias(rel_str, overrides)
    if not matched:
        return False
    # None value means "suppress this file entirely"
    if selected is None:
        return True
    # Skip if a different provider owns this file
    return alias is None or selected != alias


def _copy_mode_overlay_dir(  # noqa: PLR0913
    mode_dir: Path,
    staging_dir: Path,
    *,
    alias: str | None = None,
    mode_name: str,
    overrides: dict[str, str | None] | None = None,
    mapped_sources: set[str] | None = None,
    sources: dict[str, str],
) -> None:
    """Stage files from a mode-specific overlay directory.

    Unlike ``_copy_template_dir``, which expects a ``repolish/`` subdirectory,
    this function treats ``mode_dir`` itself as the template root.  Files are
    copied directly into ``staging_dir/repolish/``, overriding any previously
    staged files with the same relative path.

    This is called after the provider's main ``repolish/`` templates have been
    staged, so mode-specific files always take precedence over shared ones.

    The provider source recorded in ``sources`` is annotated as
    ``alias:mode_name`` (e.g. ``'myprovider:root'``) so callers can
    distinguish overlay-staged files from base-staged ones for display
    purposes.  The colon separator is safe because provider aliases are
    derived from directory or YAML key names and never contain colons.
    """
    if not mode_dir.is_dir():
        return

    # annotate alias so the caller can tell this file came from the overlay
    annotated_alias = f'{alias}:{mode_name}' if alias is not None else None

    dest_root = staging_dir / 'repolish'
    for item in mode_dir.rglob('*'):
        rel_str = item.relative_to(mode_dir).as_posix()
        # use original alias for override matching (overrides reference provider names)
        if _should_skip_item(item, rel_str, alias=alias, overrides=overrides):
            continue
        stripped = rel_str.removesuffix('.jinja')
        if (
            mapped_sources is not None
            and item.is_file()
            and is_conditional_file(rel_str)
            and stripped not in mapped_sources
        ):
            continue
        _copy_item_to_dest(
            item,
            mode_dir,
            dest_root,
            alias=annotated_alias,
            sources=sources,
        )


def _copy_template_dir(  # noqa: PLR0913
    template_dir: Path,
    staging_dir: Path,
    *,
    alias: str | None = None,
    overrides: dict[str, str | None] | None = None,
    mapped_sources: set[str] | None = None,
    sources: dict[str, str],
) -> None:
    """Copy the contents of a template directory into the staging directory.

    Each provider is expected to have a `repolish/` subdirectory containing
    the project layout files. These will be copied over to the staging dir under
    the staging directory root.

    Files are skipped when overrides pin them to a different provider alias,
    or when they are unmapped ``_repolish.*`` files not present in
    ``mapped_sources``.
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
        # Unmapped conditional source: skip entirely.  Files with the
        # _repolish. prefix are staging intermediates only and will never be
        # auto-applied to the project.  Only stage them when they appear in
        # mapped_sources, meaning a file_mappings entry references them.
        stripped = rel_str.removesuffix('.jinja')
        if (
            mapped_sources is not None
            and item.is_file()
            and is_conditional_file(rel_str)
            and stripped not in mapped_sources
        ):
            continue
        _copy_item_to_dest(
            item,
            repolish_dir,
            dest_root,
            alias=alias,
            sources=sources,
        )
