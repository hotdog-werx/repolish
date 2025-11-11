import difflib
import filecmp
import json
import os
import shutil
from pathlib import Path, PurePosixPath

from cookiecutter.main import cookiecutter
from hotlog import get_logger
from rich.console import Console
from rich.syntax import Syntax

from .builder import create_cookiecutter_template
from .config import RepolishConfig
from .loader import Action, Decision, Providers, create_providers
from .processors import replace_text, safe_file_read

logger = get_logger(__name__)


def build_final_providers(config: RepolishConfig) -> Providers:
    """Build the final Providers object by merging provider contributions.

    - Loads providers from config.directories
    - Merges config.context over provider.context
    - Applies config.delete_files entries (with '!' negation) on top of
      provider decisions and records provenance Decisions for config entries
    """
    providers = create_providers(config.directories)

    # Merge contexts: config wins
    merged_context = {**providers.context, **config.context}

    # Start from provider delete decisions
    delete_set = set(providers.delete_files)

    cfg_delete = config.delete_files or []
    for raw in cfg_delete:
        neg = isinstance(raw, str) and raw.startswith('!')
        entry = raw[1:] if neg else raw
        p = Path(*PurePosixPath(entry).parts)
        if neg:
            delete_set.discard(p)
        else:
            delete_set.add(p)
        # provenance source: config file path if set, else 'config'
        cfg_file = config.config_file
        src = cfg_file.as_posix() if isinstance(cfg_file, Path) else 'config'
        providers.delete_history.setdefault(p.as_posix(), []).append(
            Decision(
                source=src,
                action=(Action.keep if neg else Action.delete),
            ),
        )

    # produce final Providers-like object
    return Providers(
        context=merged_context,
        anchors=providers.anchors,
        delete_files=list(delete_set),
        delete_history=providers.delete_history,
        file_mappings=providers.file_mappings,
        create_only_files=providers.create_only_files,
    )


def prepare_staging(config: RepolishConfig) -> tuple[Path, Path, Path]:
    """Compute and ensure staging dirs next to the config file.

    Returns: (base_dir, setup_input_path, setup_output_path)
    """
    cfg_file = config.config_file
    base_dir = Path(cfg_file).resolve().parent if cfg_file else Path.cwd()
    staging = base_dir / '.repolish'
    setup_input = staging / 'setup-input'
    setup_output = staging / 'setup-output'

    # clear output dir if present
    shutil.rmtree(setup_input, ignore_errors=True)
    shutil.rmtree(setup_output, ignore_errors=True)
    setup_input.mkdir(parents=True, exist_ok=True)
    setup_output.mkdir(parents=True, exist_ok=True)

    return base_dir, setup_input, setup_output


def prepare_template(setup_input: Path, template_dirs: list[Path]) -> None:
    """Prepare the merged cookiecutter template in setup_input by copying/merging.

    Provided template directories are merged into `setup_input`.
    """
    # Delegate to builder helper which knows how to merge provider templates
    create_cookiecutter_template(setup_input, template_dirs)


def preprocess_templates(
    setup_input: Path,
    providers: Providers,
    config: RepolishConfig,
    base_dir: Path,
) -> None:
    """Apply anchor-driven replacements to files under setup_input.

    Local project files used for anchor-driven overrides are resolved relative
    to `base_dir` (usually the directory containing the config file).
    """
    anchors_mapping = {**providers.anchors, **config.anchors}

    for tpl in setup_input.rglob('*'):
        if not tpl.is_file():
            continue
        try:
            tpl_text = tpl.read_text(encoding='utf-8', errors='replace')
        except (OSError, UnicodeDecodeError) as exc:
            # skip binary or unreadable files but log at debug level
            logger.debug(
                'unreadable_template_file',
                template_file=tpl,
                error=str(exc),
            )
            continue
        rel = tpl.relative_to(
            setup_input / '{{cookiecutter._repolish_project}}',
        )
        local_path = base_dir / rel
        local_text = safe_file_read(local_path)
        # Let replace_text raise if something unexpected happens; caller will log
        new_text = replace_text(
            tpl_text,
            local_text,
            anchors_dictionary=anchors_mapping,
        )
        if new_text != tpl_text:
            tpl.write_text(new_text, encoding='utf-8')


def render_template(
    setup_input: Path,
    providers: Providers,
    setup_output: Path,
) -> None:
    """Run cookiecutter once on the merged template (setup_input) into setup_output."""
    # Dump the merged context into the merged template so cookiecutter can
    # read it from disk (avoids requiring each provider to ship cookiecutter.json).
    # Inject a special variable `_repolish_project` used by the staging step
    # so providers can place the project layout under a `repolish/` folder and
    # we copy it to `{{cookiecutter._repolish_project}}` in the staging dir.
    merged_ctx = dict(providers.context)
    # default project folder name used during generation
    merged_ctx.setdefault('_repolish_project', 'repolish')

    ctx_file = setup_input / 'cookiecutter.json'
    ctx_file.write_text(
        json.dumps(merged_ctx, ensure_ascii=False),
        encoding='utf-8',
    )

    cookiecutter(str(setup_input), no_input=True, output_dir=str(setup_output))


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
    a_text = a_raw.decode('utf-8', errors='replace').replace('\r\n', '\n').replace('\r', '\n')
    b_text = b_raw.decode('utf-8', errors='replace').replace('\r\n', '\n').replace('\r', '\n')
    if a_text == b_text:
        return True, [], []
    return (
        False,
        a_text.splitlines(keepends=True),
        b_text.splitlines(keepends=True),
    )


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

        # Skip files starting with _repolish. prefix
        if rel_str.startswith('_repolish.'):
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
                lineterm='',
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
            lineterm='',
        ),
    )
    return (dest_path, ud)


def _check_file_mappings(
    file_mappings: dict[str, str],
    delete_files: set[str],
    setup_output: Path,
    base_dir: Path,
    *,
    preserve: bool,
) -> list[tuple[str, str]]:
    """Check file_mappings for diffs between sources and destinations.

    Returns list of (relative_path, message_or_diff).
    """
    diffs: list[tuple[str, str]] = []

    for dest_path, source_path in file_mappings.items():
        # Skip files marked for deletion (they'll be checked separately)
        if dest_path in delete_files:
            continue

        result = _check_single_file_mapping(
            dest_path,
            source_path,
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
    mapped_sources = set(providers.file_mappings.values())
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
            providers.file_mappings,
            delete_files_set,
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

        # Skip files starting with _repolish. prefix
        if rel_str.startswith('_repolish.'):
            continue

        # Skip files that are source files in file_mappings or existing create-only files
        if rel_str in skip_sources:
            continue

        dest = base_dir / rel

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out, dest)


def _apply_file_mappings(
    file_mappings: dict[str, str],
    setup_output: Path,
    base_dir: Path,
) -> None:
    """Process file_mappings: copy source -> destination with rename."""
    for dest_path, source_path in file_mappings.items():
        source_file = setup_output / 'repolish' / source_path
        if not source_file.exists():
            logger.warning(
                'file_mapping_source_not_found',
                source=source_path,
                dest=dest_path,
            )
            continue

        dest_file = base_dir / dest_path
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, dest_file)


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
    mapped_sources = set(providers.file_mappings.values())
    create_only_files_set = {p.as_posix() for p in providers.create_only_files}

    # Build skip set: include create-only files that already exist in the project
    skip_sources = mapped_sources.copy()
    for rel_str in create_only_files_set:
        if (base_dir / rel_str).exists():
            skip_sources.add(rel_str)

    # Copy regular files (skip _repolish.* prefix, mapped sources, and existing create-only files)
    _apply_regular_files(
        output_files,
        setup_output,
        skip_sources,
        base_dir,
    )

    # Process file_mappings: copy source -> destination with rename
    _apply_file_mappings(
        providers.file_mappings,
        setup_output,
        base_dir,
    )

    # Now apply deletions at the project root as the final step
    for rel in providers.delete_files:
        target = base_dir / rel
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()


def rich_print_diffs(diffs: list[tuple[str, str]]) -> None:
    """Print diffs using rich formatting.

    Args:
        diffs: List of tuples (relative_path, message_or_unified_diff)
    """
    console = Console()
    for rel, msg in diffs:
        console.rule(f'[bold]{rel}')
        if msg in ('MISSING', 'PRESENT_BUT_SHOULD_BE_DELETED'):
            console.print(msg)
        else:
            # highlight as a diff
            syntax = Syntax(msg, 'diff', theme='ansi_dark', word_wrap=False)
            console.print(syntax)
