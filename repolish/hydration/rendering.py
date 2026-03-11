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

from repolish.loader import FileMode, Providers, TemplateMapping
from repolish.misc import ctx_to_dict

logger = get_logger(__name__)


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
    providers: Providers
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
            context=ctx_to_use,
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
    return None


def _ctx_for_pid(pid: str | None, providers: Providers) -> dict:
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


def _collect_skip_templates(providers: Providers) -> set[str]:
    """Identify templates that are rendered later with per-mapping context.

    `TemplateMapping` entries are processed after the generic render pass,
    so we skip them during the initial walk to avoid rendering the same file
    twice.
    """
    return {
        v.source_template
        for v in providers.file_mappings.values()
        if isinstance(v, TemplateMapping) and v.source_template and v.file_mode != FileMode.DELETE
    }


def render_template(
    setup_input: Path,
    providers: Providers,
    setup_output: Path,
) -> None:
    """Dispatch rendering to Jinja2.

    Errors from both the Jinja pass and the mapping pass are collected and
    raised together as a single :class:`RuntimeError` so callers see all
    failures at once rather than stopping at the first bad template.
    """
    skip_templates = _collect_skip_templates(providers)

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
    providers: Providers,
    dest_path: str,
) -> str | None:
    """Return the template text or None and remove the mapping on failure."""
    if not template_file.exists():
        logger.warning(
            'file_mapping_template_not_found',
            template=str(template_file),
            dest=dest_path,
        )
        providers.file_mappings.pop(dest_path, None)
        return None
    try:
        return template_file.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as exc:
        logger.exception(
            'file_mapping_template_unreadable',
            template=str(template_file),
            error=str(exc),
        )
        providers.file_mappings.pop(dest_path, None)
        return None


def _render_single_mapping(
    dest_path: str,
    mapping: TemplateMapping,
    ctx: RenderContext,
) -> None:
    """Render and materialize a single TemplateMapping entry.

    `ctx` is a :class:`RenderContext` instance.  Previously we passed a
    raw dict containing the same five values; using the dataclass improves
    type checking and reduces boilerplate unpacking.
    """
    setup_input: Path = ctx.setup_input
    setup_output: Path = ctx.setup_output
    providers: Providers = ctx.providers

    if mapping.file_mode == FileMode.DELETE:
        providers.file_mappings.pop(dest_path, None)
        return

    src_template = mapping.source_template
    if not src_template:
        providers.file_mappings.pop(dest_path, None)
        return

    project_root = setup_input / 'repolish'
    template_file = project_root / src_template
    txt = _load_and_validate_template(template_file, providers, dest_path)
    if txt is None:
        return

    env = Environment(
        autoescape=select_autoescape(['html', 'xml'], default_for_string=False),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )

    base_ctx = _ctx_for_pid(mapping.source_provider, providers)
    # compose context for rendering and delegate
    render_ctx = {**base_ctx, **ctx_to_dict(mapping.extra_context)}
    try:
        rendered = _jinja_render(
            env,
            txt,
            render_ctx,
            filename=template_file,
        )
    except UndefinedError as exc:
        # log the template and destination path so the error is easy to locate.
        logger.error(  # noqa: TRY400
            'mapping_template_undefined_error',
            template=str(template_file),
            dest=dest_path,
            error=str(exc),
        )
        msg = f'{exc} (while rendering mapping {src_template} for {dest_path})'
        raise UndefinedError(msg) from exc

    # when materializing a mapping we don't want the generated file to
    # appear with the bare destination name. prefixing the *filename* itself
    # with `_repolish.` lets us easily identify mapping outputs in the
    # staging area (for debugging) and keeps the regular rendering logic from
    # treating them as normal template files. the prefix is stripped when the
    # mapping is applied to the project tree.
    prefix = '_repolish.'
    orig = Path(dest_path)
    prefixed_name = prefix + orig.name
    target = setup_output / 'repolish' / orig.parent / prefixed_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding='utf-8')

    # Normalize mapping so downstream code still thinks the source is the
    # unprefixed destination path; the helpers in comparison/application will
    # look for the prefixed file when they need it.
    providers.file_mappings[dest_path] = dest_path


def _process_template_mappings(
    ctx: RenderContext,
) -> None:
    """Render and materialize `TemplateMapping`-valued file_mappings into setup-output."""
    errors: list[str] = []

    for dest_path, source_val in list(ctx.providers.file_mappings.items()):
        if not isinstance(source_val, TemplateMapping):
            continue
        try:
            _render_single_mapping(dest_path, source_val, ctx)
        except Exception as exc:  #  noqa: BLE001 -- catch any rendering-related failure
            # store the destination and the exception message for later
            errors.append(f'{dest_path}: {exc}')

    if errors:
        joined = '\n'.join(errors)
        raise RuntimeError('errors rendering template mappings:\n' + joined)
