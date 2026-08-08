import shutil
from dataclasses import dataclass
from pathlib import Path

from hotlog import get_logger

from repolish.config import RepolishConfig
from repolish.preprocessors import replace_text, safe_file_read
from repolish.providers import SessionBundle, TemplateMapping
from repolish.utils import ensure_dot_repolish

logger = get_logger(__name__)


@dataclass(frozen=True)
class _PreprocessContext:
    """Context object for preprocessing operations.

    Groups together the common parameters needed for preprocessing
    to reduce function argument count and improve maintainability.
    """

    setup_input: Path
    base_dir: Path
    anchors: dict[str, str]


def prepare_staging(config: RepolishConfig) -> tuple[Path, Path, Path]:
    """Compute and ensure staging dirs next to the config file.

    Returns: (base_dir, setup_input_path, setup_output_path)
    """
    base_dir = config.config_dir
    staging = ensure_dot_repolish(base_dir)
    setup_input = staging / '_' / 'stage'
    setup_output = staging / '_' / 'render'

    # Clear transient outputs from previous runs while preserving provider-info
    # registration files (provider-info.*.json, .all-providers.json) so that
    # providers don't get re-linked on every apply.
    shutil.rmtree(setup_input, ignore_errors=True)
    shutil.rmtree(setup_output, ignore_errors=True)
    promote_dir = staging / '_' / 'promote'
    shutil.rmtree(promote_dir, ignore_errors=True)
    scratch = staging / '_'
    if scratch.exists():
        for f in scratch.glob('provider-context.*.json'):
            f.unlink(missing_ok=True)
    setup_input.mkdir(parents=True, exist_ok=True)
    setup_output.mkdir(parents=True, exist_ok=True)

    return base_dir, setup_input, setup_output


def _preprocess_single_file(
    tpl_path: Path,
    local_path: Path,
    anchors: dict[str, str],
) -> None:
    """Apply anchor-driven preprocessing to a single template file.

    Args:
        tpl_path: Path to the staged template file.
        local_path: Path to the local project file for anchor extraction.
        anchors: Base anchors from create_anchors().
    """
    try:
        tpl_text = tpl_path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as exc:
        logger.debug(
            'skipping_unreadable_file',
            template_file=str(tpl_path),
            error=str(exc),
        )
        return

    local_text = safe_file_read(local_path)
    new_text = replace_text(tpl_text, local_text, anchors_dictionary=anchors)

    if new_text != tpl_text:
        tpl_path.write_text(new_text, encoding='utf-8')
        tpl_path.chmod(tpl_path.stat().st_mode)


def _get_source_template(source_val: str | TemplateMapping) -> str | None:
    """Extract source template path from a mapping entry.

    Returns None for DELETE/SUPPRESS modes or invalid entries.
    """
    if isinstance(source_val, TemplateMapping):
        if not source_val.source_template:
            return None
        if source_val.file_mode.value in ('delete', 'suppress'):
            return None
        return source_val.source_template
    return str(source_val)


@dataclass(frozen=True)
class _MappingPreprocessContext:
    """Context for preprocessing a single mapping entry."""

    tpl_path: Path
    dest_path: str
    source_val: str | TemplateMapping
    source_template: str
    mappings_dict: dict[str, str | TemplateMapping]
    ctx: _PreprocessContext


def _apply_preprocessing(args: _MappingPreprocessContext) -> None:
    """Apply preprocessing for a single mapping entry."""
    try:
        tpl_text = args.tpl_path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as exc:
        logger.debug(
            'skipping_unreadable_file',
            template_file=str(args.tpl_path),
            error=str(exc),
        )
        return

    local_path = args.ctx.base_dir / args.dest_path
    local_text = safe_file_read(local_path)
    new_text = replace_text(
        tpl_text,
        local_text,
        anchors_dictionary=args.ctx.anchors,
    )

    if new_text != tpl_text and isinstance(args.source_val, TemplateMapping):
        dest_safe = args.dest_path.replace('/', '_').replace('\\', '_')
        source_name = Path(args.source_template).name
        preproc_name = f'_preproc_{dest_safe}_{source_name}'
        preproc_path = args.ctx.setup_input / 'repolish' / preproc_name
        preproc_path.write_text(new_text, encoding='utf-8')
        preproc_path.chmod(args.tpl_path.stat().st_mode)
        args.mappings_dict[args.dest_path] = TemplateMapping(
            source_template=args.source_val.source_template,
            extra_context=args.source_val.extra_context,
            file_mode=args.source_val.file_mode,
            source_provider=args.source_val.source_provider,
            preprocessed_source=preproc_name,
        )
        logger.info(
            'created_preprocessed_copy',
            source=args.source_val.source_template,
            preprocessed=preproc_name,
            destination=args.dest_path,
        )
    elif new_text != tpl_text:
        args.tpl_path.write_text(new_text, encoding='utf-8')
        args.tpl_path.chmod(args.tpl_path.stat().st_mode)


def _process_mapping_entry(
    dest_path: str,
    source_val: str | TemplateMapping,
    mappings_dict: dict[str, str | TemplateMapping],
    ctx: _PreprocessContext,
) -> tuple[str | None, bool]:
    """Process a single mapping entry (string or TemplateMapping).

    Returns:
        Tuple of (source_template_path, is_suppressed).
        source_template_path is None if skipped entirely.
        is_suppressed is True if the mapping has SUPPRESS mode.
    """
    source_template = _get_source_template(source_val)
    if not source_template:
        # Check if this is a suppressed mapping (returns None for suppress/delete)
        if isinstance(source_val, TemplateMapping) and source_val.file_mode.value == 'suppress':
            return (None, True)
        return (None, False)

    tpl_path = ctx.setup_input / 'repolish' / source_template
    if not tpl_path.exists():
        logger.warning(
            'template_not_found_for_preprocessing',
            template=str(tpl_path),
            destination=dest_path,
        )
        return (None, False)

    _apply_preprocessing(
        _MappingPreprocessContext(
            tpl_path=tpl_path,
            dest_path=dest_path,
            source_val=source_val,
            source_template=source_template,
            mappings_dict=mappings_dict,
            ctx=ctx,
        ),
    )
    return (source_template, False)


def _process_mappings_phase(
    mappings_dict: dict[str, str | TemplateMapping],
    ctx: _PreprocessContext,
) -> tuple[set[str], set[str]]:
    """Process all entries in a mappings dictionary.

    Returns:
        Tuple of (mapped_sources, suppressed_sources).
        mapped_sources: templates that were preprocessed.
        suppressed_sources: templates marked as SUPPRESS to exclude from auto-staging.
    """
    mapped_sources: set[str] = set()
    suppressed_sources: set[str] = set()
    for dest_path, source_val in list(mappings_dict.items()):
        source_template, is_suppressed = _process_mapping_entry(
            dest_path,
            source_val,
            mappings_dict,
            ctx,
        )
        if is_suppressed:
            if isinstance(source_val, TemplateMapping) and source_val.source_template:
                suppressed_sources.add(source_val.source_template)
        elif source_template:
            mapped_sources.add(source_template)
    return (mapped_sources, suppressed_sources)


def _process_auto_staged_templates(
    setup_input: Path,
    mapped_sources: set[str],
    suppressed_sources: set[str],
    ctx: _PreprocessContext,
) -> None:
    """Process auto-staged templates not referenced by any mapping.

    These use the original behavior: local file at same relative path.
    Templates marked as SUPPRESS are also excluded from auto-staging.
    """
    for tpl in (setup_input / 'repolish').rglob('*'):
        if not tpl.is_file():
            continue
        rel_str = tpl.relative_to(setup_input / 'repolish').as_posix()
        if rel_str in mapped_sources or rel_str in suppressed_sources:
            continue
        local_path = ctx.base_dir / rel_str
        _preprocess_single_file(tpl, local_path, ctx.anchors)


def preprocess_templates(
    setup_input: Path,
    providers: SessionBundle,
    base_dir: Path,
) -> None:
    """Apply anchor-driven replacements to files under setup_input.

    Local project files used for anchor-driven overrides are resolved relative
    to `base_dir` (usually the directory containing the config file).
    Anchors originate exclusively from provider `create_anchors()` implementations.

    For TemplateMapping entries, preprocessing uses the destination file's
    local content to extract anchor values. When one template maps to multiple
    destinations, each destination gets its own preprocessed copy named with
    a prefix that encodes the destination path.

    For auto-staged templates and plain string mappings, the template is
    preprocessed in-place using the local file at the destination path.
    """
    # Build context object once and pass it around
    ctx = _PreprocessContext(
        setup_input=setup_input,
        base_dir=base_dir,
        anchors=providers.anchors,
    )

    # Track which source templates are used by mappings
    # so we don't preprocess them twice
    mapped_sources: set[str] = set()
    suppressed_sources: set[str] = set()

    # Phase 1: Process file_mappings
    mapped, suppressed = _process_mappings_phase(providers.file_mappings, ctx)
    mapped_sources.update(mapped)
    suppressed_sources.update(suppressed)

    # Phase 2: Process promoted_file_mappings
    mapped, suppressed = _process_mappings_phase(providers.promoted_file_mappings, ctx)
    mapped_sources.update(mapped)
    suppressed_sources.update(suppressed)

    # Phase 3: Process auto-staged templates (not referenced by any mapping)
    _process_auto_staged_templates(setup_input, mapped_sources, suppressed_sources, ctx)
