import json
from pathlib import Path
from shutil import copy2
from typing import cast

from cookiecutter.main import cookiecutter
from hotlog import get_logger
from jinja2 import (
    Environment,
    StrictUndefined,
    TemplateSyntaxError,
    select_autoescape,
)
from pydantic import BaseModel

from repolish.config.models import RepolishConfig
from repolish.loader import Providers
from repolish.loader.types import FileMode, TemplateMapping

logger = get_logger(__name__)


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


def render_with_jinja(
    setup_input: Path,
    merged_ctx: dict,
    setup_output: Path,
    skip_templates: set[str] | None = None,
) -> None:
    """Render staged templates with Jinja2.

    The merged context is exposed under the `cookiecutter` namespace so
    existing templates continue to work unchanged.

    Args:
        setup_input: staging `setup-input` path containing the merged template.
        merged_ctx: merged provider context (available to templates).
        setup_output: staging `setup-output` path where rendered files are written.
        skip_templates: optional set of relative template paths (POSIX strings)
            to skip during the generic rendering pass (used for templates that
            will be rendered later with additional per-mapping context).
    """
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

        try:
            rendered_rel = _render_path_parts(env, rel, merged_ctx)
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

        try:
            # Make the merged context available both as top-level variables
            # and under `cookiecutter` for backward compatibility.
            rendered_txt = env.from_string(txt).render(
                **merged_ctx,
                cookiecutter=merged_ctx,
            )
        except TemplateSyntaxError as exc:
            logger.exception(
                'template_content_syntax_error',
                file=str(src),
                error=str(exc),
            )
            raise

        dest.write_text(rendered_txt, encoding='utf-8')


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


def render_template(
    setup_input: Path,
    providers: Providers,
    setup_output: Path,
    config: RepolishConfig,
) -> None:
    """Dispatch rendering to Jinja or cookiecutter based on runtime config."""
    merged_ctx = dict(providers.context)
    merged_ctx.setdefault('_repolish_project', 'repolish')

    # Collect templates that must be skipped during the generic render pass
    # because they will be rendered later with per-mapping extra context.
    # We expect `TemplateMapping` instances for per-file extra context.

    skip_templates = {
        v.source_template
        for v in providers.file_mappings.values()
        if isinstance(v, TemplateMapping) and v.source_template and v.file_mode != FileMode.DELETE
    }

    # If provider-scoped mapping rendering is requested, enforce that *all*
    # providers are migrated. This is a strict, opt-in breaking behaviour so
    # callers must explicitly mark providers as migrated (module-level
    # `provider_migrated = True`) before enabling the feature.
    if getattr(config, 'provider_scoped_template_context', False):
        unmigrated = [p for p, m in providers.provider_migrated.items() if not m]
        if unmigrated:
            msg = (
                'provider_scoped_template_context=True requires all providers to be migrated; '
                f'unmigrated providers: {unmigrated}'
            )
            raise RuntimeError(msg)

    if config.no_cookiecutter:
        render_with_jinja(
            setup_input,
            merged_ctx,
            setup_output,
            skip_templates=skip_templates,
        )
    else:
        if skip_templates:  # pragma: no cover -- cookiecutter path not supported for per-file TemplateMapping
            msg = 'TemplateMapping entries require config.no_cookiecutter=True'
            raise RuntimeError(msg)
        render_with_cookiecutter(setup_input, merged_ctx, setup_output)

    # Materialize TemplateMapping entries (render template per-mapping using
    # merged_ctx + extra_ctx) in a helper to keep `render_template` small.
    _process_template_mappings(
        setup_input,
        setup_output,
        providers,
        merged_ctx,
        use_provider_context=bool(
            getattr(config, 'provider_scoped_template_context', False),
        ),
    )


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


def _extra_context_to_dict(extra_ctx: object | None) -> dict[str, object]:
    """Normalize typed or untyped extra-context into a plain dict.

    Accepts Pydantic models or plain dicts; unknown types and None map to
    an empty dict to preserve rendering stability.
    """
    if isinstance(extra_ctx, BaseModel):
        return cast('dict[str, object]', extra_ctx.model_dump())
    if isinstance(extra_ctx, dict):
        # only module style  providers may hit this branch.
        return cast(
            'dict[str, object]',
            extra_ctx,
        )  # pragma: no cover -- branch to be removed in v1
    return {}


def _render_mapping_text(
    env: Environment,
    txt: str,
    base_ctx: dict,
    extra_ctx: object,
) -> str:
    """Render mapping text with a base context (either merged or provider-scoped) and per-mapping extra context."""
    extra_ctx_dict = _extra_context_to_dict(extra_ctx)
    render_ctx = {**base_ctx, **extra_ctx_dict}
    # Pass merged-style `cookiecutter` namespace for backward compatibility
    return env.from_string(txt).render(**render_ctx, cookiecutter=base_ctx)


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
      captured context. Otherwise raises a RuntimeError.
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

    # development-only error path; once all providers are migrated this
    # branch will never be hit and the associated message can be removed. we
    # mark it ``no cover`` so tests aren't forced to simulate an unmigrated
    # provider just to satisfy coverage tools.
    msg = (  # pragma: no cover
        f'provider {source_provider!r} is not migrated; '
        'enable provider_migrated=True on the provider before using '
        'provider_scoped_template_context'
    )
    raise RuntimeError(msg)  # pragma: no cover


def _render_single_mapping(
    dest_path: str,
    mapping: TemplateMapping,
    ctx: dict,
) -> None:
    """Render and materialize a single TemplateMapping entry.

    `ctx` is a small context dict containing: setup_input, setup_output,
    providers, merged_ctx and use_provider_context. Packing into `ctx`
    keeps the arg-count low and the function easy to call from the loop.
    """
    setup_input: Path = ctx['setup_input']
    setup_output: Path = ctx['setup_output']
    providers: Providers = ctx['providers']
    merged_ctx: dict = ctx['merged_ctx']
    use_provider_context: bool = ctx['use_provider_context']

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
    rendered = _render_mapping_text(env, txt, base_ctx, mapping.extra_context)

    target = setup_output / str(merged_ctx.get('_repolish_project', 'repolish')) / dest_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding='utf-8')

    # Normalize mapping so downstream code sees a string source path
    providers.file_mappings[dest_path] = dest_path


def _process_template_mappings(
    setup_input: Path,
    setup_output: Path,
    providers: Providers,
    merged_ctx: dict,
    *,
    use_provider_context: bool = False,
) -> None:
    """Render and materialize `TemplateMapping`-valued file_mappings into setup-output.

    Implementation delegates per-mapping work to helpers to reduce the
    overall cognitive complexity of the function.
    """
    ctx = {
        'setup_input': setup_input,
        'setup_output': setup_output,
        'providers': providers,
        'merged_ctx': merged_ctx,
        'use_provider_context': use_provider_context,
    }

    for dest_path, source_val in list(providers.file_mappings.items()):
        if not isinstance(source_val, TemplateMapping):
            continue
        _render_single_mapping(dest_path, source_val, ctx)
