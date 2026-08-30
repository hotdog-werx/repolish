from dataclasses import dataclass
from pathlib import Path
from shutil import copy2

from hotlog import get_logger
from jinja2 import (
    Environment,
    StrictUndefined,
    TemplateSyntaxError,
    UndefinedError,
    select_autoescape,
)

from repolish.directives import FilePair
from repolish.hydration.mapping_resolution import resolve_mappings
from repolish.misc import ctx_to_dict
from repolish.providers import FileMode, SessionBundle, TemplateMapping

logger = get_logger(__name__)


class _BinaryFile:
    """Sentinel type returned when a template file cannot be decoded as UTF-8.

    Using a dedicated class (rather than a plain ``object()`` instance) lets
    type checkers narrow ``str | _BinaryFile | None`` correctly after the
    ``if isinstance(txt, _BinaryFile)`` guard.
    """


# Module-level singleton; callers compare with ``isinstance`` for type safety.
_BINARY_FILE = _BinaryFile()


@dataclass
class RenderContext:
    """Container for arguments needed by template rendering.

    The class groups together paths, contexts, providers, and configuration
    so that callers can pass a single object instead of a long argument list.
    Consumers access attributes rather than dictionary keys, which improves
    type checking, IDE completion, and avoids silent typos.  This is much
    cleaner than a plain `dict` when multiple related values travel through
    several helper functions.
    """

    setup_input: Path
    setup_output: Path
    providers: SessionBundle
    skip_templates: set[str] | None = None


def _render_path_parts(env: Environment, rel: Path, ctx: dict) -> Path:
    """Render each part of a Path using Jinja and return a Path object."""
    rendered_parts: list[str] = []
    for part in rel.parts:
        # Render path component (supports templated directory/filenames).
        tpl = env.from_string(part)
        rendered = tpl.render(**ctx)
        rendered_parts.append(rendered)
    return Path(*rendered_parts)


def render_with_jinja(ctx: RenderContext) -> None:
    """Render staged templates with Jinja2.

    Templates are rendered with the provider's own captured context.
    When a file can be traced back to its declaring provider via the provenance
    map recorded during staging, that provider's context is used; otherwise
    rendering falls back to an empty context.

    Args:
        ctx: A `RenderContext` instance containing all material needed for
            rendering.  Fields are documented on the class itself and include
            paths, the merged context dict, the provider collection, and a
            set of templates to skip.  `skip_templates` is
            optional and mirrors the previous behaviour.
    """
    # `RenderContext` provides attribute access instead of dictionary
    # lookups, which avoids key typos and improves autocomplete support in
    # editors.
    setup_input = ctx.setup_input
    setup_output = ctx.setup_output
    # `providers` is available on `ctx` and only used
    # indirectly via helpers; no need to create a local variable here.
    skip_templates = ctx.skip_templates
    render_errors: list[tuple[str, str]] = []

    template_root = setup_input / 'repolish'

    env = Environment(
        autoescape=select_autoescape(['html', 'xml'], default_for_string=False),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )

    for src in template_root.rglob('*'):
        if src.is_dir():
            continue
        rel = src.relative_to(template_root)
        rel_str = rel.as_posix()

        # Skip templates that will be rendered separately with extra mapping-specific context
        if skip_templates and rel_str in skip_templates:
            logger.debug('skipping_template_for_later_render', template=rel_str)
            continue

        # pick the appropriate context for this file
        ctx_to_use = _choose_ctx_for_file(rel_str, ctx)
        logger.debug(
            'rendering_file',
            file=str(src),
            provider=ctx.providers.template_sources.get(rel_str),
        )

        error = _render_file(env, src, rel, ctx_to_use, setup_output)
        if error is not None:
            render_errors.append((rel_str, error))

    if render_errors:
        lines = [f'{f}: {m}' for f, m in render_errors]
        raise RuntimeError('template rendering errors:\n' + '\n'.join(lines))


def _render_file(
    env: Environment,
    src: Path,
    rel: Path,
    ctx_to_use: dict,
    setup_output: Path,
) -> str | None:
    """Render one staged template file into *setup_output*.

    Returns an error string when the file cannot be rendered, or ``None``
    when rendering succeeds.  Binary files are copied unchanged.
    """
    try:
        rendered_rel = _render_path_parts(env, rel, ctx_to_use)
    except TemplateSyntaxError as exc:
        logger.error(  # noqa: TRY400
            'template_path_syntax_error',
            file=str(src),
            error=str(exc),
        )
        return f'path syntax error: {exc}'

    dest = setup_output / 'repolish' / rendered_rel
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        txt = src.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        copy2(src, dest)
        return None

    try:
        rendered_txt = _jinja_render(env, txt, ctx_to_use, filename=src)
    except (UndefinedError, TemplateSyntaxError) as exc:
        return str(exc)
    dest.write_text(rendered_txt, encoding='utf-8')
    dest.chmod(src.stat().st_mode)
    return None


def _ctx_for_pid(pid: str | None, providers: SessionBundle) -> dict:
    """Return the context dict for the given provider id.

    Returns an empty dict when ``pid`` is ``None`` or not found in
    ``provider_contexts``; rendering falls back to an empty context for
    templates with no declared provider owner.
    """
    if pid:
        found = providers.provider_contexts.get(pid)
        if found is not None:
            return ctx_to_dict(found)
    return {}


def _choose_ctx_for_file(rel_str: str, ctx: RenderContext) -> dict:
    """Return the context to use when rendering a generic staged file.

    Extracted to reduce complexity of the main rendering function.
    """
    # Use the declaring provider's own context when the template has a known
    # provider source; fall back to the merged context otherwise.
    pid = ctx.providers.template_sources.get(rel_str)
    # provider_ids are expected to be POSIX-formatted, but earlier versions of
    # the code sometimes exposed raw Windows paths (backslashes).  normalise
    # before consulting the migration map so lookups succeed even if upstream
    # producers were inconsistent.  `get` defaults to False to avoid the
    # mysterious `null` value in the logs that triggered this investigation.
    if pid:
        clean = pid.replace('\\', '/')
        norm_pid = Path(clean).as_posix()
    else:
        norm_pid = None
    logger.debug(
        'choose_context_for_file',
        rel=rel_str,
        pid=pid,
        normalized_pid=norm_pid,
    )
    return _ctx_for_pid(norm_pid, ctx.providers)


def _jinja_render(
    env: Environment,
    txt: str,
    ctx: dict,
    *,
    filename: Path,
) -> str:
    """Render `txt` with `env` and `ctx`.

    Errors during rendering are logged and wrapped with `filename` so the
    caller gets actionable messages. `ctx` is exposed as top-level Jinja variables.
    """
    try:
        return env.from_string(txt).render(**ctx)
    except TemplateSyntaxError as exc:
        # syntax errors indicate bad template markup; log file and message so
        # the caller can surface a clean error without a verbose context dump.
        logger.error(  # noqa: TRY400
            'template_content_syntax_error',
            file=str(filename),
            error=str(exc),
        )
        raise
    except UndefinedError as exc:
        # undefined variables indicate a missing context key; log the file
        # path so the error location is clear without dumping the full context.
        logger.error(  # noqa: TRY400
            'template_content_undefined_error',
            file=str(filename),
            error=str(exc),
        )
        msg = f'{exc} (while rendering {filename})'
        raise UndefinedError(msg) from exc


def _add_mapping_to_skip_set(
    dest_path: str,
    v: TemplateMapping,
    paused_files: frozenset[str],
    skip_set: set[str],
) -> None:
    """Add appropriate skip entries for a single mapping.

    Note: DELETE mode branch is not covered - caller (_collect_skip_templates)
    filters out DELETE mappings before calling this helper, so this branch
    is unreachable by design.
    """
    if v.file_mode == FileMode.DELETE:  # pragma: no cover
        return
    if dest_path in paused_files:
        if v.preprocessed_source:
            skip_set.add(v.preprocessed_source)
    else:
        source = v.source_template
        if source:
            skip_set.add(source)
        if v.preprocessed_source:
            skip_set.add(v.preprocessed_source)


def _collect_skip_templates(providers: SessionBundle) -> set[str]:
    """Identify templates that are rendered later with per-mapping context.

    `TemplateMapping` entries are processed after the generic render pass,
    so we skip them during the initial walk to avoid rendering the same file
    twice.  Both ``file_mappings`` and ``promoted_file_mappings`` contribute
    to the skip set; promoted mappings carry their own ``extra_context`` and
    must not be rendered in the generic pass without it.

    For TemplateMapping entries with preprocessed_source (created for
    multi-destination templates with keep-blocks), the preprocessed_source
    path is also added to the skip set.

    Paused files are also added to the skip set to prevent rendering errors
    when the user has temporarily paused a file. For paused files with
    preprocessed_source, the preprocessed_source is added to the skip set
    so it's not rendered by the generic pass.
    """
    resolution = resolve_mappings(providers)
    skip_set: set[str] = set()
    paused_files = providers.paused_files

    for mappings in (resolution.regular_mappings, resolution.promoted_mappings):
        for dest_path, v in mappings.items():
            if not isinstance(v, TemplateMapping) or not v.source_template:
                continue
            _add_mapping_to_skip_set(dest_path, v, paused_files, skip_set)
    return skip_set


def render_template(
    setup_input: Path,
    providers: SessionBundle,
    setup_output: Path,
) -> None:
    """Dispatch rendering to Jinja2.

    Errors from both the Jinja pass and the mapping pass are collected and
    raised together as a single :class:`RuntimeError` so callers see all
    failures at once rather than stopping at the first bad template.
    """
    skip_templates = _collect_skip_templates(providers) | providers.suppressed_sources

    # build a RenderContext once; the same object drives both
    # the Jinja pass and the mapping pass.
    render_ctx = RenderContext(
        setup_input=setup_input,
        setup_output=setup_output,
        providers=providers,
        skip_templates=skip_templates,
    )

    all_errors: list[str] = []

    try:
        render_with_jinja(render_ctx)
    except RuntimeError as exc:
        all_errors.append(str(exc))

    # Materialize TemplateMapping entries, rendering each with the declaring
    # provider's own context merged with any mapping-level extra_context.
    try:
        _process_template_mappings(render_ctx)
    except RuntimeError as exc:
        all_errors.append(str(exc))

    if all_errors:
        raise RuntimeError('\n'.join(all_errors))


def _load_and_validate_template(
    template_file: Path,
    mappings: dict[str, str | TemplateMapping],
    dest_path: str,
) -> str | _BinaryFile | None:
    """Return the template text, ``_BINARY_FILE``, or ``None``.

    Returns ``_BINARY_FILE`` when the file exists but cannot be decoded as
    UTF-8 (i.e. it is a binary asset such as an image).  The caller is
    responsible for copying the file unchanged in that case.

    Returns ``None`` and removes the mapping when the file cannot be read
    due to an OS-level error. ``mappings`` is the specific dict
    (``file_mappings`` or ``promoted_file_mappings``) that owns this entry
    so the pop targets the right collection.

    Note: File existence is checked by the caller via
    ``TemplateMapping.resolve_template_path()``, which raises
    ``FileNotFoundError`` if the template is not found.
    """
    try:
        return template_file.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        # Binary file (e.g. image): the caller will copy it unchanged.
        logger.debug(
            'file_mapping_template_is_binary',
            template=str(template_file),
            dest=dest_path,
        )
        return _BinaryFile()
    except OSError as exc:
        logger.exception(
            'file_mapping_template_unreadable',
            template=str(template_file),
            error=str(exc),
        )
        mappings.pop(dest_path, None)
        return None


def _render_single_mapping(
    dest_path: str,
    mapping: TemplateMapping,
    ctx: RenderContext,
    mappings: dict[str, str | TemplateMapping],
) -> None:
    """Render and materialize a single TemplateMapping entry."""
    providers: SessionBundle = ctx.providers

    # Handle delete mode or missing source
    if mapping.file_mode == FileMode.DELETE or not mapping.source_template:
        mappings.pop(dest_path, None)
        return

    # Resolve template file path
    project_root = ctx.setup_input / 'repolish'
    template_file = _get_template_file_path(mapping, project_root)
    if template_file is None:
        providers.file_mappings.pop(dest_path, None)
        return

    # Load template content
    txt = _load_and_validate_template(template_file, mappings, dest_path)
    # Note: txt is None when file is unreadable (OS error) - _load_and_validate_template
    # already logged the error and removed the mapping. This branch is not covered
    # because simulating file read failures requires mocking at a low level.
    if txt is None:  # pragma: no cover
        return

    # Prepare output path
    target = _get_target_path(dest_path, ctx.setup_output)
    target.parent.mkdir(parents=True, exist_ok=True)

    # Handle binary vs text templates
    if isinstance(txt, _BinaryFile):
        copy2(template_file, target)
    else:
        rendered = _render_template_text(
            txt,
            template_file,
            dest_path,
            mapping,
            providers,
        )
        target.write_text(rendered, encoding='utf-8')

    # Update mapping for downstream processing
    mappings[dest_path] = TemplateMapping(
        source_template=dest_path,
        file_mode=mapping.file_mode,
        source_provider=mapping.source_provider,
    )


def _get_template_file_path(
    mapping: TemplateMapping,
    project_root: Path,
) -> Path | None:
    """Resolve template file path from mapping.

    Note: Error branches (file not found) are not covered - these represent
    exceptional conditions where staging integrity is violated (preprocessed
    file missing after successful staging, or template path resolution fails).
    Testing these would require corrupting the staging directory mid-run.
    """
    if mapping.preprocessed_source:
        template_file = project_root / mapping.preprocessed_source
        if not template_file.exists():  # pragma: no cover
            logger.exception(
                'preprocessed_source_not_found',
                preprocessed_source=mapping.preprocessed_source,
                project_root=str(project_root),
            )
            return None
        return template_file

    try:
        return mapping.resolve_template_path(project_root)
    except FileNotFoundError:  # pragma: no cover
        logger.exception(
            'template_file_not_found',
            source_template=mapping.source_template,
            project_root=str(project_root),
        )
        return None


def _get_target_path(dest_path: str, setup_output: Path) -> Path:
    """Compute target output path with _repolish. prefix."""
    prefix = '_repolish.'
    return setup_output / 'repolish' / Path(dest_path).parent / (prefix + Path(dest_path).name)


def rendered_file_pairs(
    setup_output: Path,
    base_dir: Path,
) -> list[FilePair]:
    """Pair rendered output files with their local destination counterparts.

    Reverses :func:`_get_target_path`: every file under
    ``setup_output / 'repolish'`` pairs with the same relative path under
    *base_dir*, minus the ``_repolish.`` filename prefix. Pairing is
    staging-layout knowledge belonging to hydration; the preprocessor node
    only consumes the resulting pairs (see :func:`repolish.directives.run_phase`).
    """
    rendered_root = setup_output / 'repolish'
    pairs: list[FilePair] = []
    if not rendered_root.exists():
        return pairs
    prefix = '_repolish.'
    for rendered_file in rendered_root.rglob('*'):
        if not rendered_file.is_file():
            continue
        parts = list(rendered_file.relative_to(rendered_root).parts)
        if parts[-1].startswith(prefix):
            parts[-1] = parts[-1].removeprefix(prefix)
        pairs.append(
            FilePair(
                template_path=rendered_file,
                local_path=base_dir / Path(*parts),
            ),
        )
    return pairs


def _render_template_text(
    txt: str,
    template_file: Path,
    dest_path: str,
    mapping: TemplateMapping,
    providers: SessionBundle,
) -> str:
    """Render text template with provider context and extra_context."""
    env = Environment(
        autoescape=select_autoescape(['html', 'xml'], default_for_string=False),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )

    base_ctx = _ctx_for_pid(mapping.source_provider, providers)
    render_ctx = {**base_ctx, **ctx_to_dict(mapping.extra_context)}

    try:
        return _jinja_render(env, txt, render_ctx, filename=template_file)
    except UndefinedError as exc:
        logger.exception(
            'mapping_template_undefined_error',
            template=str(template_file),
            dest=dest_path,
            error=str(exc),
        )
        src = mapping.source_template
        msg = f'{exc} (while rendering mapping {src} for {dest_path})'
        raise UndefinedError(msg) from exc


def _process_mapping_dict(
    mappings: dict[str, str | TemplateMapping],
    ctx: RenderContext,
    paused_files: frozenset[str],
    errors: list[str],
) -> None:
    """Process a single mapping dict (either regular or promoted)."""
    for dest_path, source_val in list(mappings.items()):
        if not isinstance(source_val, TemplateMapping):
            continue
        if dest_path in paused_files:
            logger.info(
                'skipping_paused_file_mapping',
                dest=dest_path,
                _display_level=1,
            )
            continue
        _try_render_mapping(dest_path, source_val, ctx, mappings, errors)


def _process_template_mappings(
    ctx: RenderContext,
) -> None:
    """Render and materialize `TemplateMapping`-valued entries into setup-output.

    Iterates over both ``file_mappings`` and ``promoted_file_mappings`` so
    that promoted templates carrying their own ``extra_context`` are rendered
    with the correct context instead of being skipped or rendered with an
    empty context during the generic Jinja pass.

    Paused files are skipped entirely - they are not rendered.
    """
    errors: list[str] = []
    resolution = resolve_mappings(ctx.providers)
    paused_files = ctx.providers.paused_files

    _process_mapping_dict(
        resolution.regular_mappings,
        ctx,
        paused_files,
        errors,
    )
    _process_mapping_dict(
        resolution.promoted_mappings,
        ctx,
        paused_files,
        errors,
    )

    if errors:
        raise RuntimeError(
            'errors rendering template mappings:\n' + '\n'.join(errors),
        )


def _try_render_mapping(
    dest_path: str,
    source_val: TemplateMapping,
    ctx: RenderContext,
    mappings: dict[str, str | TemplateMapping],
    errors: list[str],
) -> None:
    """Render a mapping, collecting errors instead of raising."""
    try:
        _render_single_mapping(dest_path, source_val, ctx, mappings)
    except Exception as exc:  # noqa: BLE001
        errors.append(f'{dest_path}: {exc}')
