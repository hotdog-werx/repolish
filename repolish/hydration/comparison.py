import difflib
import filecmp
import os
from pathlib import Path

from hotlog import get_logger

from repolish.loader import Providers

from .context import _is_conditional_file

logger = get_logger(__name__)


def collect_output_files(setup_output: Path) -> list[Path]:
    """Return a list of file Paths under `setup_output`."""
    return [p for p in setup_output.rglob('*') if p.is_file()]


def _preserve_line_endings() -> bool:
    """Return True when REPOLISH_PRESERVE_LINE_ENDINGS is truthy in env.

    Centralized to make behavior testable and reduce complexity in the main
    comparison function.
    """
    val = os.getenv('REPOLISH_PRESERVE_LINE_ENDINGS', '')
    return str(val).lower() in ('1', 'true', 'yes')


def _compare_and_prepare_diff(
    out: Path,
    dest: Path,
    *,
    preserve: bool,
) -> tuple[bool, list[str], list[str]]:
    """Compare two files and return (same, a_lines, b_lines).

    - same: True when files are equal according to the chosen policy.
    - a_lines, b_lines: lists of lines (with line endings) to be used in a
      unified diff when same is False. When same is True these values are
      empty lists.
    """
    if preserve:
        # fast-path equality check using filecmp (may be optimized by OS)
        if filecmp.cmp(out, dest, shallow=False):
            return True, [], []
        a_raw = out.read_bytes()
        b_raw = dest.read_bytes()
        a_text = a_raw.decode('utf-8', errors='replace')
        b_text = b_raw.decode('utf-8', errors='replace')
        return (
            False,
            a_text.splitlines(keepends=True),
            b_text.splitlines(keepends=True),
        )

    # Normalized comparison (ignore CRLF vs LF)
    a_raw = out.read_bytes()
    b_raw = dest.read_bytes()

    # Try to decode as text, if it fails treat as binary
    try:
        a_text = a_raw.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
        b_text = b_raw.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
        if a_text == b_text:
            return True, [], []
        return (
            False,
            a_text.splitlines(keepends=True),
            b_text.splitlines(keepends=True),
        )
    except UnicodeDecodeError:
        # Binary files - compare raw bytes
        return (a_raw == b_raw), [], []


def _check_regular_files(
    output_files: list[Path],
    setup_output: Path,
    skip_files: set[str],
    base_dir: Path,
    *,
    preserve: bool,
) -> list[tuple[str, str]]:
    """Check regular files (non-conditional, non-mapped) for diffs.

    Args:
        output_files: List of files in the template output.
        setup_output: Path to the cookiecutter output directory.
        skip_files: Set of file paths to skip (mapped sources + delete files + create-only existing files).
        base_dir: Base directory where the project root is located.
        preserve: Whether to preserve line endings during comparison.

    Returns list of (relative_path, message_or_diff).
    """
    diffs: list[tuple[str, str]] = []

    for out in output_files:
        rel = out.relative_to(setup_output / 'repolish')
        rel_str = rel.as_posix()

        # Skip conditional files (files with _repolish. prefix anywhere in path)
        if _is_conditional_file(rel_str):
            continue

        # Skip files that are mapped sources, marked for deletion, or create-only files that exist
        if rel_str in skip_files:
            continue

        dest = base_dir / rel

        if not dest.exists():
            diffs.append((rel_str, 'MISSING'))
            continue

        same, a_lines, b_lines = _compare_and_prepare_diff(
            out,
            dest,
            preserve=preserve,
        )
        if same:
            continue

        ud = ''.join(
            difflib.unified_diff(
                b_lines,
                a_lines,
                fromfile=str(dest),
                tofile=str(out),
                lineterm='\n',
            ),
        )
        diffs.append((rel_str, ud))

    return diffs


def _check_single_file_mapping(
    dest_path: str,
    source_path: str,
    setup_output: Path,
    base_dir: Path,
    *,
    preserve: bool,
) -> tuple[str, str] | None:
    """Check a single file mapping for diffs.

    Returns (dest_path, message_or_diff) tuple if there's a diff, None if same.
    """
    source_file = setup_output / 'repolish' / source_path
    if not source_file.exists():
        return (dest_path, f'MAPPING_SOURCE_MISSING: {source_path}')

    dest_file = base_dir / dest_path

    if not dest_file.exists():
        return (dest_path, 'MISSING')

    same, a_lines, b_lines = _compare_and_prepare_diff(
        source_file,
        dest_file,
        preserve=preserve,
    )
    if same:
        return None

    ud = ''.join(
        difflib.unified_diff(
            b_lines,
            a_lines,
            fromfile=str(dest_file),
            tofile=f'{source_path} -> {dest_path}',
            lineterm='\n',
        ),
    )
    return (dest_path, ud)


def _check_file_mappings(
    providers: Providers,
    setup_output: Path,
    base_dir: Path,
    *,
    preserve: bool,
) -> list[tuple[str, str]]:
    """Check file_mappings for diffs between sources and destinations.

    Args:
        providers: Providers object with file_mappings, delete_files, and create_only_files.
        setup_output: Path to the cookiecutter output directory.
        base_dir: Base directory where the project root is located.
        preserve: Whether to preserve line endings when comparing files.

    Returns list of (relative_path, message_or_diff).
    """
    diffs: list[tuple[str, str]] = []
    delete_files_set = {p.as_posix() for p in providers.delete_files}
    create_only_files_set = {p.as_posix() for p in providers.create_only_files}

    for dest_path, source_path in providers.file_mappings.items():
        # Skip files marked for deletion (they'll be checked separately)
        if dest_path in delete_files_set:
            continue

        # Skip create-only files that already exist (no diff should be shown)
        if dest_path in create_only_files_set and (base_dir / dest_path).exists():
            continue

        # Normalize tuple-valued mappings to the source string for checking
        src = source_path[0] if isinstance(source_path, tuple) else source_path

        result = _check_single_file_mapping(
            dest_path,
            src,
            setup_output,
            base_dir,
            preserve=preserve,
        )
        if result:
            diffs.append(result)

    return diffs


def check_generated_output(
    setup_output: Path,
    providers: Providers,
    base_dir: Path,
) -> list[tuple[str, str]]:
    """Compare generated output to project files and report diffs and deletions.

    Returns a list of (relative_path, message_or_unified_diff). Empty when no diffs found.
    """
    output_files = collect_output_files(setup_output)
    diffs: list[tuple[str, str]] = []

    preserve = _preserve_line_endings()
    mapped_sources = {v for v in providers.file_mappings.values() if isinstance(v, str)}
    delete_files_set = {str(p) for p in providers.delete_files}
    create_only_files_set = {p.as_posix() for p in providers.create_only_files}

    # Build skip set: include create-only files that already exist in the project
    skip_files = mapped_sources | delete_files_set
    for rel_str in create_only_files_set:
        if (base_dir / rel_str).exists():
            skip_files.add(rel_str)

    # Check regular files (skip _repolish.* prefix, mapped sources, delete files, and existing create-only files)
    diffs.extend(
        _check_regular_files(
            output_files,
            setup_output,
            skip_files,
            base_dir,
            preserve=preserve,
        ),
    )

    # Check file_mappings: compare mapped source files to their destinations
    diffs.extend(
        _check_file_mappings(
            providers,
            setup_output,
            base_dir,
            preserve=preserve,
        ),
    )

    # provider-declared deletions: if a path is expected deleted but exists in
    # the project, surface that so devs know to run repolish
    for rel in providers.delete_files:
        proj_target = base_dir / rel
        if proj_target.exists():
            diffs.append((rel.as_posix(), 'PRESENT_BUT_SHOULD_BE_DELETED'))

    return diffs
