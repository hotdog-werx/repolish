import json
from pathlib import Path
from shutil import copy2

from cookiecutter.main import cookiecutter
from hotlog import get_logger
from jinja2 import (
    Environment,
    StrictUndefined,
    TemplateSyntaxError,
    select_autoescape,
)

from repolish.config.models import RepolishConfig
from repolish.loader import Providers

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
    skip_templates = {
        v[0] for v in providers.file_mappings.values() if isinstance(v, tuple) and v and isinstance(v[0], str)
    }

    if config.no_cookiecutter:
        render_with_jinja(
            setup_input,
            merged_ctx,
            setup_output,
            skip_templates=skip_templates,
        )
    else:
        if skip_templates:  # pragma: no cover -- this section will go away no point on testing
            msg = 'tuple-valued file_mappings require config.no_cookiecutter=True'
            raise RuntimeError(msg)
        render_with_cookiecutter(setup_input, merged_ctx, setup_output)

    # Materialize tuple-valued mappings (render template per-mapping using
    # merged_ctx + extra_ctx) in a helper to keep `render_template` small.
    _process_tuple_file_mappings(
        setup_input,
        setup_output,
        providers,
        merged_ctx,
    )


def _process_tuple_file_mappings(
    setup_input: Path,
    setup_output: Path,
    providers: Providers,
    merged_ctx: dict,
) -> None:
    """Render and materialize tuple-valued file_mappings into setup-output.

    Each tuple mapping is of the form (source_template, extra_context). We
    render the template with merged_ctx updated by extra_context and write
    the result to the staged `setup-output` under the expected destination
    path so downstream checks/apply can treat the mapping as a normal file.
    """
    project_root = setup_input / '{{cookiecutter._repolish_project}}'
    project_name = str(merged_ctx.get('_repolish_project', 'repolish'))

    for dest_path, source_val in list(providers.file_mappings.items()):
        if not (isinstance(source_val, tuple) and len(source_val) == 2):
            continue

        src_template, extra_ctx = source_val
        template_file = project_root / src_template
        if not template_file.exists():  # pragma: no cover -- see below
            # will be caught by earlier existence check in render_with_jinja
            logger.warning(
                'file_mapping_template_not_found',
                template=str(template_file),
                dest=dest_path,
            )
            providers.file_mappings.pop(dest_path, None)
            continue

        try:
            txt = template_file.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as exc:  # pragma: no cover -- see below
            # will be caught by earlier existence check in render_with_jinja
            logger.exception(
                'file_mapping_template_unreadable',
                template=str(template_file),
                error=str(exc),
            )
            providers.file_mappings.pop(dest_path, None)
            continue

        env = Environment(
            autoescape=select_autoescape(
                ['html', 'xml'],
                default_for_string=False,
            ),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )

        render_ctx = {**merged_ctx, **(extra_ctx or {})}
        rendered = env.from_string(txt).render(
            **render_ctx,
            cookiecutter=merged_ctx,
        )

        target = setup_output / project_name / dest_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding='utf-8')

        # Normalize mapping so downstream code sees a string source path
        providers.file_mappings[dest_path] = dest_path
