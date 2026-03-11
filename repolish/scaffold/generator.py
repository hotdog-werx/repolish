"""Scaffold generator for new repolish provider packages.

Derives package name and class name from the repo/provider name supplied by
the user, then renders Jinja templates stored alongside this module into the
requested output directory.  Existing files are silently skipped so the
command is safe to run multiple times without clobbering work in progress.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_TEMPLATES_DIR = Path(__file__).parent / 'templates'


@dataclass(frozen=True)
class ScaffoldContext:
    """Derived names used to render every scaffold template.

    ``short_prefix`` is the title-cased last segment of the package name and
    forms the common prefix for all generated class names.  For example, a
    package named ``codeguide_iac`` yields ``short_prefix='Iac'`` and the
    classes ``IacProvider``, ``IacProviderContext``, ``IacProviderInputs``.
    """

    repo_name: str
    package_name: str
    short_prefix: str
    class_name: str
    context_class: str
    inputs_class: str


def _derive_context(name: str) -> ScaffoldContext:
    """Derive all class names from a repo/provider name.

    The ``short_prefix`` is the title-cased last segment of the package name.

    Examples:
    --------
    >>> _derive_context('codeguide-workspace')
    ScaffoldContext(repo_name='codeguide-workspace',
                    package_name='codeguide_workspace',
                    short_prefix='Workspace',
                    class_name='WorkspaceProvider',
                    context_class='WorkspaceProviderContext',
                    inputs_class='WorkspaceProviderInputs')
    """
    package_name = name.replace('-', '_')
    short_prefix = package_name.split('_')[-1].capitalize()
    return ScaffoldContext(
        repo_name=name,
        package_name=package_name,
        short_prefix=short_prefix,
        class_name=f'{short_prefix}Provider',
        context_class=f'{short_prefix}ProviderContext',
        inputs_class=f'{short_prefix}ProviderInputs',
    )


def _output_path(template_rel: Path, package_name: str) -> Path:
    """Map a template's relative path to its rendered output path.

    Rules:
    - Strip the trailing ``.jinja`` extension.
    - Replace the leading ``package`` path component with the actual
      ``package_name`` so that ``package/repolish/models.py.jinja``
      becomes ``{package_name}/repolish/models.py``.
    """
    parts = list(template_rel.parts)
    if parts[0] == 'package':
        parts[0] = package_name
    out = Path(*parts)
    if out.suffix == '.jinja':
        out = out.with_suffix('')
    return out


def _collect_templates() -> list[Path]:
    """Return all ``.jinja`` template paths relative to the templates root."""
    return [p.relative_to(_TEMPLATES_DIR) for p in _TEMPLATES_DIR.rglob('*.jinja')]


def generate(name: str, output_dir: Path) -> list[Path]:
    """Render all scaffold templates into *output_dir*.

    Args:
        name: Provider/repo name (e.g. ``codeguide-workspace``).
        output_dir: Directory to write files into.  Created automatically.

    Returns:
        List of paths that were written (skipped files are not included).
    """
    ctx = _derive_context(name)
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        keep_trailing_newline=True,
        autoescape=False,  # noqa: S701 — code templates, not HTML; XSS irrelevant
    )
    context_dict = {
        'repo_name': ctx.repo_name,
        'package_name': ctx.package_name,
        'short_prefix': ctx.short_prefix,
        'class_name': ctx.class_name,
        'context_class': ctx.context_class,
        'inputs_class': ctx.inputs_class,
    }

    written: list[Path] = []
    for template_rel in sorted(_collect_templates()):
        out_rel = _output_path(template_rel, ctx.package_name)
        dest = output_dir / out_rel
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        rendered = env.get_template(template_rel.as_posix()).render(
            context_dict,
        )
        dest.write_text(rendered, encoding='utf-8')
        written.append(dest)

    return written
