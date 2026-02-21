import shutil
from pathlib import Path

from hotlog import get_logger

from repolish.hydration.comparison import collect_output_files
from repolish.hydration.context import _is_conditional_file
from repolish.hydration.misc import get_source_str_from_mapping
from repolish.loader import Providers
from repolish.loader.types import TemplateMapping

logger = get_logger(__name__)


def _apply_regular_files(
    output_files: list[Path],
    setup_output: Path,
    skip_sources: set[str],
    base_dir: Path,
) -> None:
    """Copy regular files (non-conditional, non-mapped) to base_dir.

    Args:
        output_files: List of files in the template output.
        setup_output: Path to the cookiecutter output directory.
        skip_sources: Set of file paths to skip (file_mappings sources + existing create-only files).
        base_dir: Base directory where the project root is located.
    """
    for out in output_files:
        rel = out.relative_to(setup_output / 'repolish')
        rel_str = rel.as_posix()

        # Skip conditional files (files with _repolish. prefix anywhere in path)
        if _is_conditional_file(rel_str):
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
        logger.info(
            'copying_file',
            source=str(out),
            dest=str(dest),
            rel=rel_str,
            _display_level=1,
        )
        shutil.copy2(out, dest)


def _copy_mapping_file(
    dest_path: str,
    source_str: str,
    setup_output: Path,
    base_dir: Path,
    create_only_files_set: set[str],
) -> None:
    """Copy the resolved source string into the destination path (handles logging)."""
    source_file = setup_output / 'repolish' / source_str
    if not source_file.exists():
        logger.warning(
            'file_mapping_source_not_found',
            source=source_str,
            dest=dest_path,
        )
        return

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
        return

    dest_file.parent.mkdir(parents=True, exist_ok=True)
    logger.info(
        'copying_file_mapping',
        source=source_str,
        dest=dest_path,
        target_path=str(dest_file),
        _display_level=1,
    )
    shutil.copy2(source_file, dest_file)


def _apply_file_mappings(
    file_mappings: dict[str, str | TemplateMapping],
    setup_output: Path,
    base_dir: Path,
    create_only_files_set: set[str],
) -> None:
    """Process file_mappings: copy source -> destination with rename.

    Implementation delegates validation and copy work to small helpers to
    keep cognitive complexity low while preserving behavior.
    """
    for dest_path, source_path in file_mappings.items():
        source_str = get_source_str_from_mapping(source_path)
        # When mapping has no source (e.g. TemplateMapping with None) skip
        if not source_str:
            if isinstance(source_path, TemplateMapping):
                # warn rather than debug so misconfigured providers are visible
                logger.warning('mapping_without_source', dest=dest_path)
            continue

        _copy_mapping_file(
            dest_path,
            source_str,
            setup_output,
            base_dir,
            create_only_files_set,
        )


def apply_generated_output(
    setup_output: Path,
    providers: Providers,
    base_dir: Path,
) -> None:
    """Copy generated files into the project root and apply deletions.

    Args:
        setup_output: Path to the cookiecutter output directory.
        providers: Providers object with delete_files list and file_mappings.
        base_dir: Base directory where the project root is located.

    Returns None. Exceptions during per-file operations are raised to caller.
    """
    output_files = collect_output_files(setup_output)
    mapped_sources = {v for v in providers.file_mappings.values() if isinstance(v, str)}
    create_only_files_set = {p.as_posix() for p in providers.create_only_files}

    logger.info(
        'apply_generated_output_starting',
        create_only_files=sorted(create_only_files_set),
        file_mappings=providers.file_mappings,
        _display_level=1,
    )

    # Build skip set: include create-only files that already exist in the project
    skip_sources = mapped_sources.copy()
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
    _apply_regular_files(
        output_files,
        setup_output,
        skip_sources,
        base_dir,
    )

    # Process file_mappings: copy source -> destination with rename
    # Respect create_only_files for mapped destinations too
    _apply_file_mappings(
        providers.file_mappings,
        setup_output,
        base_dir,
        create_only_files_set,
    )

    # Now apply deletions at the project root as the final step
    for rel in providers.delete_files:
        target = base_dir / rel
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
