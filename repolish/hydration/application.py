import filecmp
import shutil
from pathlib import Path

from hotlog import get_logger

from repolish.hydration.comparison import collect_output_files
from repolish.hydration.misc import get_source_str_from_mapping
from repolish.misc import is_conditional_file
from repolish.providers import SessionBundle, TemplateMapping

logger = get_logger(__name__)


def _apply_regular_files(
    output_files: list[Path],
    setup_output: Path,
    skip_sources: set[str],
    base_dir: Path,
    *,
    disable_auto_staging: bool = False,
) -> dict[str, str]:
    """Copy regular files (non-conditional, non-mapped) to base_dir.

    Returns a dict mapping POSIX relative path to ``'written'`` or
    ``'unchanged'`` for each file that was processed.

    Args:
        output_files: List of files in the template output.
        setup_output: Path to the rendered output directory.
        skip_sources: Set of file paths to skip (file_mappings sources + existing create-only files).
        base_dir: Base directory where the project root is located.
        disable_auto_staging: When True, skip all auto-staged files (used for
            monorepo root passes where every output file must be explicitly
            declared via ``create_file_mappings``).
    """
    status: dict[str, str] = {}
    for out in output_files:
        rel = out.relative_to(setup_output / 'repolish')
        rel_str = rel.as_posix()

        # Root monorepo pass: all auto-staging is disabled — providers must
        # map every file explicitly via create_file_mappings.
        if disable_auto_staging:
            logger.debug('auto_staging_disabled_skipping_file', file=rel_str)
            continue

        # Skip conditional files (files with _repolish. prefix anywhere in path)
        if is_conditional_file(rel_str):
            logger.debug('skipping_repolish_prefix_file', file=rel_str)
            continue

        # Skip files that are source files in file_mappings or existing create-only files
        if rel_str in skip_sources:
            logger.info(
                'skipping_file',
                file=rel_str,
                reason='in_skip_sources',
                _display_level=1,
            )
            continue

        dest = base_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)

        if dest.exists() and filecmp.cmp(str(out), str(dest), shallow=False):
            status[rel_str] = 'unchanged'
        else:
            logger.info(
                'copying_file',
                source=str(out),
                dest=str(dest),
                rel=rel_str,
                _display_level=1,
            )
            shutil.copy2(out, dest)
            status[rel_str] = 'written'
    return status


def _copy_mapping_file(
    dest_path: str,
    source_str: str,
    setup_output: Path,
    base_dir: Path,
    create_only_files_set: set[str],
) -> str | None:
    """Copy the resolved source string into the destination path (handles logging).

    Returns ``'written'``, ``'unchanged'``, or ``None`` when the source is missing.
    """
    # mapping sources are materialized with a filename prefix; attempt to
    # load the prefixed file first and fall back to the original name if the
    # prefix isn't present (compatibility with older runs).
    prefix = '_repolish.'
    source_file = setup_output / 'repolish' / source_str
    if not source_file.exists():
        cand = Path(source_str)
        prefixed = setup_output / 'repolish' / cand.parent / (prefix + cand.name)
        if prefixed.exists():
            source_file = prefixed
        else:
            logger.warning(
                'file_mapping_source_not_found',
                source=source_str,
                dest=dest_path,
            )
            return None

    dest_file = base_dir / dest_path
    # Respect create-only semantics
    if dest_path in create_only_files_set and dest_file.exists():
        logger.info(
            'create_only_file_mapping_exists_skipping',
            dest=dest_path,
            source=source_str,
            target_path=str(dest_file),
            _display_level=1,
        )
        return 'unchanged'

    dest_file.parent.mkdir(parents=True, exist_ok=True)

    if dest_file.exists() and filecmp.cmp(
        str(source_file),
        str(dest_file),
        shallow=False,
    ):
        return 'unchanged'

    logger.info(
        'copying_file_mapping',
        source=source_str,
        dest=dest_path,
        target_path=str(dest_file),
        _display_level=1,
    )
    shutil.copy2(source_file, dest_file)
    return 'written'


def _apply_file_mappings(
    file_mappings: dict[str, str | TemplateMapping],
    setup_output: Path,
    base_dir: Path,
    create_only_files_set: set[str],
) -> dict[str, str]:
    """Process file_mappings: copy source -> destination with rename.

    Returns a dict mapping destination POSIX path to ``'written'`` or
    ``'unchanged'`` for each mapping processed.

    Implementation delegates validation and copy work to small helpers to
    keep cognitive complexity low while preserving behavior.
    """
    status: dict[str, str] = {}
    for dest_path, source_path in file_mappings.items():
        source_str = get_source_str_from_mapping(source_path)
        # When mapping has no source (e.g. TemplateMapping with None) skip
        if not source_str:
            if isinstance(source_path, TemplateMapping):
                # warn rather than debug so misconfigured providers are visible
                logger.warning('mapping_without_source', dest=dest_path)
            continue

        result = _copy_mapping_file(
            dest_path,
            source_str,
            setup_output,
            base_dir,
            create_only_files_set,
        )
        if result is not None:
            status[dest_path] = result
    return status


def apply_generated_output(
    setup_output: Path,
    providers: SessionBundle,
    base_dir: Path,
    *,
    paused_files: frozenset[str] = frozenset(),
    disable_auto_staging: bool = False,
) -> dict[str, str]:
    """Copy generated files into the project root and apply deletions.

    Returns a dict mapping POSIX destination path to one of ``'written'``,
    ``'unchanged'``, or ``'deleted'`` for every file that was processed.
    Files skipped for other reasons (suppressed, paused, etc.) are not
    included — callers can inspect
    :func:`~repolish.commands.apply.display._file_skip_reason` to determine
    why a file was excluded.

    Args:
        setup_output: Path to the rendered output directory.
        providers: SessionBundle object with delete_files list and file_mappings.
        base_dir: Base directory where the project root is located.
        paused_files: POSIX-style paths that repolish must not touch this run.
        disable_auto_staging: When True, only files declared in
            ``create_file_mappings`` are written.  Auto-staged files (those
            present in the provider's ``repolish/`` tree but not explicitly
            mapped) are silently skipped.  Set this for monorepo root passes.
    """
    output_files = collect_output_files(setup_output)
    mapped_sources = {s for v in providers.file_mappings.values() if (s := get_source_str_from_mapping(v)) is not None}
    create_only_files_set = {p.as_posix() for p in providers.create_only_files}

    logger.info(
        'apply_generated_output_starting',
        create_only_files=sorted(create_only_files_set),
        file_mappings=providers.file_mappings,
        _display_level=1,
    )

    # Build skip set: include create-only files that already exist in the project
    # Also skip sources that providers explicitly suppressed via a None mapping.
    skip_sources = mapped_sources | paused_files | providers.suppressed_sources
    for rel_str in create_only_files_set:
        target_exists = (base_dir / rel_str).exists()
        if target_exists:
            skip_sources.add(rel_str)
            logger.info(
                'create_only_file_exists_skipping',
                file=rel_str,
                target_path=str(base_dir / rel_str),
                _display_level=1,
            )
        else:
            logger.info(
                'create_only_file_missing_will_create',
                file=rel_str,
                target_path=str(base_dir / rel_str),
                _display_level=1,
            )

    # Copy regular files (skip _repolish.* prefix, mapped sources, and existing create-only files)
    file_status = _apply_regular_files(
        output_files,
        setup_output,
        skip_sources,
        base_dir,
        disable_auto_staging=disable_auto_staging,
    )

    # Process file_mappings: copy source -> destination with rename
    # Respect create_only_files for mapped destinations too
    file_status |= _apply_file_mappings(
        providers.file_mappings,
        setup_output,
        base_dir,
        create_only_files_set,
    )

    # Now apply deletions at the project root as the final step
    file_status |= _apply_deletions(
        providers.delete_files,
        base_dir,
        paused_files,
    )
    return file_status


def _apply_deletions(
    delete_files: list,
    base_dir: Path,
    paused_files: frozenset[str],
) -> dict[str, str]:
    """Delete provider-declared files from the project root, skipping paused ones.

    Returns a dict mapping POSIX path to ``'deleted'`` for each file removed.
    """
    status: dict[str, str] = {}
    for rel in delete_files:
        if rel.as_posix() in paused_files:
            continue
        target = base_dir / rel
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            status[rel.as_posix()] = 'deleted'
    return status
