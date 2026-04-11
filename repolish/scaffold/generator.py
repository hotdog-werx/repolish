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
    package named ``devkit_iac`` yields ``short_prefix='Iac'`` and the
    classes ``IacProvider``, ``IacProviderContext``, ``IacProviderInputs``.

    ``pkg_dir`` is the filesystem path for the package directory:
    ``Path('devkit_workspace')`` (flat) or ``Path('devkit') / 'workspace'`` (namespace).

    ``namespace_root`` is the top-level namespace directory (e.g. ``devkit``)
    for namespace packages, or ``''`` for flat packages.

    ``sub_pkg`` is the importable leaf name: same as ``package_name`` for
    flat packages, or the sub-package component (e.g. ``workspace``) for
    namespace packages.
    """

    repo_name: str
    package_name: str
    pkg_dir: Path
    namespace_root: str
    sub_pkg: str
    short_prefix: str
    class_name: str
    context_class: str
    inputs_class: str


def detect_mode(pkg_name: str) -> tuple[str, str | None, str]:
    """Detect flat vs. namespace mode from a normalised package name.

    Returns ``(mode, namespace_root, sub_pkg)`` where:

    - *mode* is ``'namespace'`` or ``'flat'``.
    - *namespace_root* is the top-level namespace component (e.g. ``'devkit'``)
      when *mode* is ``'namespace'``, otherwise ``None``.
    - *sub_pkg* is the leaf importable name (e.g. ``'workspace'``) for
      namespace packages, or the full flat name for flat packages.

    Examples::

        detect_mode('devkit_workspace')  -> ('flat', None, 'devkit_workspace')
        detect_mode('devkit.workspace')  -> ('namespace', 'devkit', 'workspace')
    """
    if '.' in pkg_name:
        parts = pkg_name.split('.', 1)
        return 'namespace', parts[0], parts[1]
    return 'flat', None, pkg_name


def _derive_context(
    package_name: str,
    prefix: str | None = None,
) -> ScaffoldContext:
    """Derive all class names from an explicit package name.

    ``prefix``, when supplied, overrides the short prefix used to form class
    names.  If omitted the last ``_``-segment of ``package_name`` is used.

    Examples:
    --------
    >>> _derive_context('devkit_workspace')
    ScaffoldContext(repo_name='devkit-workspace', package_name='devkit_workspace', ...)
    >>> _derive_context('devkit.workspace')
    ScaffoldContext(repo_name='devkit-workspace', package_name='devkit.workspace', ...)
    >>> _derive_context('devkit_workspace', prefix='workspace')
    ScaffoldContext(repo_name='devkit-workspace', package_name='devkit_workspace', ...)
    """
    pkg = package_name.replace('-', '_').lower()
    # Normalise dots: keep them so 'devkit.workspace' stays a namespace name
    mode, ns_root, sub = detect_mode(pkg)

    if mode == 'namespace' and ns_root is not None:
        repo_name = f'{ns_root}-{sub}'.replace('_', '-')
        pkg_dir: Path = Path(ns_root) / sub
        raw_prefix = prefix if prefix else sub.split('_')[-1]
    else:
        repo_name = pkg.replace('_', '-')
        pkg_dir = Path(pkg)
        raw_prefix = prefix if prefix else pkg.split('_')[-1]

    short_prefix = raw_prefix.capitalize()
    return ScaffoldContext(
        repo_name=repo_name,
        package_name=pkg,
        pkg_dir=pkg_dir,
        namespace_root=ns_root or '',
        sub_pkg=sub,
        short_prefix=short_prefix,
        class_name=f'{short_prefix}Provider',
        context_class=f'{short_prefix}ProviderContext',
        inputs_class=f'{short_prefix}ProviderInputs',
    )


def _output_path(template_rel: Path, pkg_dir: Path) -> Path:
    """Map a template's relative path to its rendered output path.

    Rules:
    - Strip the trailing ``.jinja`` extension.
    - Replace the leading ``package`` path component with *pkg_dir* so that
      ``package/repolish/models.py.jinja`` becomes
      ``{pkg_dir}/repolish/models.py``.  *pkg_dir* may have multiple parts
      for namespace packages (e.g. ``Path('devkit') / 'workspace'``).
    """
    parts = list(template_rel.parts)
    if parts[0] == 'package':
        parts = list(pkg_dir.parts) + parts[1:]
    out = Path(*parts)
    if out.suffix == '.jinja':
        out = out.with_suffix('')
    return out


_MONOREPO_ONLY: frozenset[str] = frozenset(
    {
        'package/repolish/provider/__init__.py.jinja',
        'package/repolish/provider/root.py.jinja',
        'package/repolish/provider/member.py.jinja',
        'package/repolish/provider/standalone.py.jinja',
    },
)
_SIMPLE_ONLY: frozenset[str] = frozenset(
    {
        'package/repolish/provider.py.jinja',
    },
)


def _collect_templates(*, simple: bool) -> list[Path]:
    """Return ``.jinja`` template paths relative to the templates root.

    When *simple* is ``True`` the monorepo mode-handler files are excluded and
    the flat ``provider.py.jinja`` is included instead.  When *simple* is
    ``False`` the flat provider template is excluded and the full monorepo set
    is included.
    """
    exclude = _SIMPLE_ONLY if not simple else _MONOREPO_ONLY
    return [
        p.relative_to(_TEMPLATES_DIR)
        for p in _TEMPLATES_DIR.rglob('*.jinja')
        if p.relative_to(_TEMPLATES_DIR).as_posix() not in exclude
    ]


def generate(
    package_name: str,
    output_dir: Path,
    prefix: str | None = None,
    *,
    simple: bool = True,
) -> list[Path]:
    """Render all scaffold templates into *output_dir*.

    Args:
        package_name: Python package name (e.g. ``devkit_workspace``).
        output_dir: Directory to write files into.  Created automatically.
        prefix: Optional class-name prefix override.  Defaults to the last
            ``_``-segment of ``package_name``.
        simple: When ``True`` (default) generate a single flat ``provider.py``
            with no monorepo mode handlers.  Pass ``False`` to generate the
            full ``provider/`` sub-package with ``root``, ``member``, and
            ``standalone`` handlers.

    Returns:
        List of paths that were written (skipped files are not included).
    """
    ctx = _derive_context(package_name, prefix)
    output_dir.mkdir(parents=True, exist_ok=True)
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        keep_trailing_newline=True,
        autoescape=False,  # noqa: S701 — code templates, not HTML; XSS irrelevant
    )
    context_dict = {
        'repo_name': ctx.repo_name,
        'package_name': ctx.package_name,
        'pkg_dir': ctx.pkg_dir.as_posix(),
        'namespace_root': ctx.namespace_root,
        'short_prefix': ctx.short_prefix,
        'class_name': ctx.class_name,
        'context_class': ctx.context_class,
        'inputs_class': ctx.inputs_class,
    }

    written: list[Path] = []
    for template_rel in sorted(_collect_templates(simple=simple)):
        out_rel = _output_path(template_rel, ctx.pkg_dir)
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
