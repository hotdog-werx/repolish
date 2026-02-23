import json
from dataclasses import dataclass
from pathlib import Path
from shutil import copy2

from cookiecutter.main import cookiecutter
from hotlog import get_logger
from jinja2 import (
    Environment,
    StrictUndefined,
    TemplateSyntaxError,
    UndefinedError,
    select_autoescape,
)
from pydantic import BaseModel

from repolish.config.models import RepolishConfig
from repolish.loader import Providers
from repolish.loader.types import FileMode, TemplateMapping
from repolish.misc import ctx_keys, ctx_to_dict

logger = get_logger(__name__)


@dataclass
class RenderContext:
    """Container for arguments needed by template rendering.

    The class groups together paths, contexts, providers, and configuration
    so that callers can pass a single object instead of a long argument list.
    Consumers access attributes rather than dictionary keys, which improves
    type checking, IDE completion, and avoids silent typos.  This is much
    cleaner than a plain ``dict`` when multiple related values travel through
    several helper functions.
    """

    setup_input: Path
    merged_ctx: dict
    setup_output: Path
    providers: Providers
    config: RepolishConfig
    skip_templates: set[str] | None = None
    use_provider_context: bool = False


def _render_path_parts(env: Environment, rel: Path, ctx: dict) -> Path:
    """Render each part of a Path using Jinja and return a Path object."""
    rendered_parts: list[str] = []
    for part in rel.parts:
        # Render path component (supports templated directory/filenames).
        # Provide merged context both as top-level variables and under the
        # `cookiecutter` name so templates can migrate away from the
        # `cookiecutter.` prefix gradually.
        tpl = env.from_string(part)
        rendered = tpl.render(**ctx, cookiecutter=ctx)
        rendered_parts.append(rendered)
    return Path(*rendered_parts)


def render_with_jinja(ctx: RenderContext) -> None:
    """Render staged templates with Jinja2.

    The merged context is exposed under the `cookiecutter` namespace so
    existing templates continue to work unchanged.  For any file that can be
    traced back to a migrated provider (the provenance map is recorded during
    staging), rendering uses that provider's own captured context instead of
    the merged context.  The former configuration flag
    ``provider_scoped_template_context`` is now always effectively enabled and
    only exists for legacy module adapters that need to override this behaviour.

    Args:
        ctx: A ``RenderContext`` instance containing all material needed for
            rendering.  Fields are documented on the class itself and include
            paths, the merged context dict, the provider collection, and a
            reference to the overall configuration.  ``skip_templates`` is
            optional and mirrors the previous behaviour.
    """
    # ``RenderContext`` provides attribute access instead of dictionary
    # lookups, which avoids key typos and improves autocomplete support in
    # editors.
    setup_input = ctx.setup_input
    merged_ctx = ctx.merged_ctx
    setup_output = ctx.setup_output
    # ``providers`` and ``config`` are available on ``ctx`` and only used
    # indirectly via helpers; no need to create local variables here.
    skip_templates = ctx.skip_templates

    template_root = setup_input / '{{cookiecutter._repolish_project}}'
    project_name = str(merged_ctx.get('_repolish_project', 'repolish'))

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

        try:
            rendered_rel = _render_path_parts(env, rel, ctx_to_use)
        except TemplateSyntaxError as exc:
            logger.exception(
                'template_path_syntax_error',
                file=str(src),
                error=str(exc),
            )
            raise

        dest = setup_output / project_name / rendered_rel
        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            txt = src.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            copy2(src, dest)
            continue

        rendered_txt = _jinja_render(env, txt, ctx_to_use, filename=src)
        dest.write_text(rendered_txt, encoding='utf-8')


def _choose_ctx_for_file(rel_str: str, ctx: RenderContext) -> dict:
    """Return the context to use when rendering a generic staged file.

    Extracted to reduce complexity of the main rendering function.
    """
    # Always attempt to honor a migrated provider's own context; the
    # previous implementation gated this behaviour behind the
    # ``provider_scoped_template_context`` configuration flag.  that flag is
    # now *always* effectively true (default changed to True in the config
    # model) and exists only for legacy module adapters which can override it
    # if they really need merged contexts globally.  upstream callers and
    # tests no longer need to set the flag just to enable scoping.
    pid = ctx.providers.template_sources.get(rel_str)
    if pid and ctx.providers.provider_migrated.get(pid):
        return ctx_to_dict(ctx.providers.provider_contexts.get(pid))
    return ctx.merged_ctx


def _jinja_render(
    env: Environment,
    txt: str,
    ctx: dict,
    *,
    filename: Path,
) -> str:
    """Render ``txt`` with ``env`` and ``ctx``.

    Errors during rendering are logged and wrapped with ``filename`` so the
    caller gets actionable messages. ``ctx`` becomes available both as
    top-level variables and under the ``cookiecutter`` name for backward
    compatibility with existing templates.
    """
    try:
        return env.from_string(txt).render(**ctx, cookiecutter=ctx)
    except TemplateSyntaxError as exc:
        # syntax errors are usually programmer mistakes; log the template
        # text and context to make reproduction easier.
        logger.exception(
            'template_content_syntax_error',
            file=str(filename),
            error=str(exc),
            template=txt,
            context=ctx,
        )
        raise
    except UndefinedError as exc:  # pragma: no cover - exercised by tests
        # undefined variables often indicate missing keys. include the
        # context and template in the log so users can inspect exactly what
        # was available on the failing platform (e.g. Windows CI).
        logger.exception(
            'template_content_undefined_error',
            file=str(filename),
            error=str(exc),
            template=txt,
            context=ctx,
        )
        msg = f'{exc} (while rendering {filename})'
        raise UndefinedError(msg) from exc


def render_with_cookiecutter(
    setup_input: Path,
    merged_ctx: dict,
    setup_output: Path,
) -> None:
    """Deprecated: render using cookiecutter for backward compatibility.

    This wrapper keeps the previous cookiecutter-based behaviour but is
    separated so the cookiecutter implementation can be removed in the
    future.
    """
    ctx_file = setup_input / 'cookiecutter.json'
    ctx_file.write_text(
        json.dumps(merged_ctx, ensure_ascii=False),
        encoding='utf-8',
    )

    # NOTE: cookiecutter-based rendering is deprecated internally and may be
    # removed in a future release — prefer `render_with_jinja` when possible.
    cookiecutter(str(setup_input), no_input=True, output_dir=str(setup_output))


def _compute_merged_context(providers: Providers) -> dict[str, object]:
    """Return a merged provider context with migrated keys removed.

    Extracted to keep the function small and easier to test.
    """
    merged = dict(providers.context)
    for pid, migrated in providers.provider_migrated.items():
        if not migrated:
            continue
        ctx_obj = providers.provider_contexts.get(pid)
        for k in ctx_keys(ctx_obj):
            merged.pop(k, None)

    merged.setdefault('_repolish_project', 'repolish')
    return merged


def _collect_skip_templates(providers: Providers) -> set[str]:
    """Identify templates that are rendered later with per-mapping context.

    ``TemplateMapping`` entries are processed after the generic render pass,
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
    config: RepolishConfig,
) -> None:
    """Dispatch rendering to Jinja or cookiecutter based on runtime config."""
    merged_ctx = _compute_merged_context(providers)
    skip_templates = _collect_skip_templates(providers)

    # provider-scoped context changes the base context per-mapping.  when
    # the feature is enabled we still allow unmigrated (module-adapter)
    # providers to operate using the merged context for compatibility.  this
    # behaviour allows users to migrate incrementally: class-based providers
    # may opt into the new model by setting ``provider_migrated=True`` while
    # legacy modules continue to receive a full merged context.  the
    # per-provider logic in ``_choose_base_ctx_for_mapping`` takes care of the
    # fallback, so no global validation is required here.
    #
    # (previously we raised an error if any providers were unmigrated; that
    # strictness proved too aggressive for mixed deployments.)

    # build a RenderContext once; the same object will later drive both
    # the Jinja pass and the mapping pass.  ``use_provider_context`` is
    # toggled for the second phase.
    render_ctx = RenderContext(
        setup_input=setup_input,
        merged_ctx=merged_ctx,
        setup_output=setup_output,
        providers=providers,
        config=config,
        skip_templates=skip_templates,
    )

    if config.no_cookiecutter:
        render_with_jinja(render_ctx)
    else:
        if skip_templates:  # pragma: no cover -- cookiecutter path not supported for per-file TemplateMapping
            msg = 'TemplateMapping entries require config.no_cookiecutter=True'
            raise RuntimeError(msg)
        render_with_cookiecutter(setup_input, merged_ctx, setup_output)

    # Materialize TemplateMapping entries (render template per-mapping using
    # merged_ctx + extra_ctx).  we reuse ``render_ctx`` but switch on the
    # provider-context flag; this mirrors the previous behaviour where a
    # temporary dict was created solely for the mapping helpers.
    render_ctx.use_provider_context = True
    _process_template_mappings(render_ctx)


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


def _choose_base_ctx_for_mapping(
    source_provider: str | None,
    *,
    use_provider_context: bool,
    merged_ctx: dict,
    providers: Providers,
) -> dict:
    """Return the appropriate base context for rendering a mapping.

    - If provider-scoped rendering is disabled, returns merged_ctx.
    - If enabled and the declaring provider is migrated, returns that provider's
      captured context. Unmigrated providers receive the full merged context as
      a compatibility fallback.
    """
    if not use_provider_context or not source_provider:
        return merged_ctx

    migrated = providers.provider_migrated.get(source_provider, False)
    if migrated:
        ctx = providers.provider_contexts.get(source_provider)
        if isinstance(ctx, BaseModel):
            return ctx.model_dump()
        if isinstance(ctx, dict):
            return ctx
        return merged_ctx

    # unmigrated providers simply fallback to merged context; no error raised
    return merged_ctx


def _render_single_mapping(
    dest_path: str,
    mapping: TemplateMapping,
    ctx: RenderContext,
) -> None:
    """Render and materialize a single TemplateMapping entry.

    ``ctx`` is a :class:`RenderContext` instance.  Previously we passed a
    raw dict containing the same five values; using the dataclass improves
    type checking and reduces boilerplate unpacking.
    """
    setup_input: Path = ctx.setup_input
    setup_output: Path = ctx.setup_output
    providers: Providers = ctx.providers
    merged_ctx: dict = ctx.merged_ctx
    use_provider_context: bool = ctx.use_provider_context

    if mapping.file_mode == FileMode.DELETE:
        providers.file_mappings.pop(dest_path, None)
        return

    src_template = mapping.source_template
    if not src_template:
        providers.file_mappings.pop(dest_path, None)
        return

    project_root = setup_input / '{{cookiecutter._repolish_project}}'
    template_file = project_root / src_template
    txt = _load_and_validate_template(template_file, providers, dest_path)
    if txt is None:
        return

    env = Environment(
        autoescape=select_autoescape(['html', 'xml'], default_for_string=False),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )

    base_ctx = _choose_base_ctx_for_mapping(
        mapping.source_provider,
        use_provider_context=use_provider_context,
        merged_ctx=merged_ctx,
        providers=providers,
    )
    # compose context for rendering and delegate
    render_ctx = {**base_ctx, **ctx_to_dict(mapping.extra_context)}
    try:
        rendered = _jinja_render(
            env,
            txt,
            render_ctx,
            filename=template_file,
        )
    except UndefinedError as exc:  # pragma: no cover - error path covered by new tests
        # add details about the template and destination so the user can
        # easily locate the problematic mapping.
        logger.exception(
            'mapping_template_undefined_error',
            template=str(template_file),
            dest=dest_path,
            error=str(exc),
        )
        msg = f'{exc} (while rendering mapping {src_template} for {dest_path})'
        raise UndefinedError(msg) from exc

    # when materializing a mapping we don't want the generated file to
    # appear with the bare destination name. prefixing the *filename* itself
    # with ``_repolish.`` lets us easily identify mapping outputs in the
    # staging area (for debugging) and keeps the regular rendering logic from
    # treating them as normal template files. the prefix is stripped when the
    # mapping is applied to the project tree.
    prefix = '_repolish.'
    orig = Path(dest_path)
    prefixed_name = prefix + orig.name
    target = setup_output / str(merged_ctx.get('_repolish_project', 'repolish')) / orig.parent / prefixed_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding='utf-8')

    # Normalize mapping so downstream code still thinks the source is the
    # unprefixed destination path; the helpers in comparison/application will
    # look for the prefixed file when they need it.
    providers.file_mappings[dest_path] = dest_path


def _process_template_mappings(
    ctx: RenderContext,
) -> None:
    """Render and materialize `TemplateMapping`-valued file_mappings into setup-output.

    ``ctx`` is expected to have ``merged_ctx`` and ``use_provider_context``
    filled appropriately.  Passing a dataclass avoids the untyped dictionary
    seen previously.
    """
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
