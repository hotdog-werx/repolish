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
        # Render path component (supports templated directory/filenames)
        tpl = env.from_string(part)
        rendered = tpl.render(cookiecutter=ctx)
        rendered_parts.append(rendered)
    return Path(*rendered_parts)


def render_with_jinja(
    setup_input: Path,
    merged_ctx: dict,
    setup_output: Path,
) -> None:
    """Render staged templates with Jinja2.

    The merged context is exposed under the `cookiecutter` namespace so
    existing templates continue to work unchanged.
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
            rendered_txt = env.from_string(txt).render(cookiecutter=merged_ctx)
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

    if config.no_cookiecutter:
        render_with_jinja(setup_input, merged_ctx, setup_output)
    else:
        render_with_cookiecutter(setup_input, merged_ctx, setup_output)
