"""Lint provider templates against their declared context model.

Static analysis pass:
- Load the provider (repolish.py) and obtain the finalized context model.
- Walk every file under provider_dir/repolish/ and strip preprocessor
  directives so Jinja2 can parse clean source.
- Collect all dotted access chains from the Jinja2 AST, constrained to names
  that are externally required (i.e. not loop vars or locally set vars).
- Validate each chain level-by-level against the Pydantic model fields.

Trial render pass:
- Re-render every cleaned template with the actual context dict using
  StrictUndefined to catch anything the static analysis missed.

Anchors (repolish-start/end blocks) are treated as plain text replacements and
are excluded from the lint; inserting Jinja expressions inside anchor values
is the user's own responsibility.
"""

import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union, get_args, get_origin

import jinja2
import jinja2.meta
import jinja2.nodes
from hotlog import get_logger
from jinja2 import select_autoescape
from pydantic import BaseModel
from rich.console import Console

from repolish.console import console
from repolish.preprocessors.core import replace_text
from repolish.providers import create_providers
from repolish.providers.models import SessionBundle

logger = get_logger(__name__)


@dataclass
class LintIssue:
    """A single static-analysis finding against a template."""

    template: str
    chain: str
    reason: str


@dataclass
class TemplateResult:
    """Aggregated findings for one template file."""

    path: str
    issues: list[LintIssue] = field(default_factory=list)
    render_error: str | None = None

    @property
    def ok(self) -> bool:
        """Return True when the template has no issues and rendered cleanly."""
        return not self.issues and self.render_error is None


@dataclass
class LintResult:
    """Aggregated results for an entire provider."""

    template_results: list[TemplateResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return True when every template in the provider is clean."""
        return all(r.ok for r in self.template_results)


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _resolve_chain(node: jinja2.nodes.Node) -> str | None:
    """Reconstruct a dotted access chain from nested Getattr/Name nodes.

    Returns None when the expression cannot be represented as a plain dotted
    path (e.g. computed subscripts like ``obj[var]``).
    """
    if isinstance(node, jinja2.nodes.Name):
        return node.name
    if isinstance(node, jinja2.nodes.Getattr):
        parent = _resolve_chain(node.node)
        return f'{parent}.{node.attr}' if parent is not None else None
    return None  # _resolve_chain recurses into .node which may be a Call or similar


def _collect_chains(ast: jinja2.nodes.Template) -> set[str]:
    """Return every dotted access chain appearing in the template AST."""
    chains: set[str] = set()
    for node in ast.find_all((jinja2.nodes.Name, jinja2.nodes.Getattr)):
        chain = _resolve_chain(node)
        if chain is not None:
            chains.add(chain)
    return chains


def _maximal_chains(chains: set[str]) -> set[str]:
    """Keep only chains that are not a strict prefix of another chain.

    For ``{a, a.b, a.b.c}`` this returns ``{a.b.c}`` — validating the
    longest chain implicitly covers all its prefixes.
    """
    return {c for c in chains if not any(o.startswith(c + '.') for o in chains)}


# ---------------------------------------------------------------------------
# Type resolution helpers
# ---------------------------------------------------------------------------


def _unwrap_optional(annotation: object) -> object:
    """Strip ``Optional[X]`` / ``X | None`` wrappers and return the inner type."""
    origin = get_origin(annotation)
    # typing.Union (covers Optional[X] which is Union[X, None])
    if origin is Union:
        args = [a for a in get_args(annotation) if a is not type(None)]
        return args[0] if len(args) == 1 else annotation
    # Python 3.10+ native union syntax (X | None) - Pydantic v2 normalises field
    # annotations to typing.Union before storing, so this branch is a defensive
    # fallback for non-Pydantic annotation objects passed directly.
    if isinstance(annotation, types.UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        return args[0] if len(args) == 1 else annotation
    return annotation


def _field_type(model_cls: type[BaseModel], name: str) -> object:
    """Return the unwrapped annotation for *name* on *model_cls*, or None if absent."""
    f = model_cls.model_fields.get(name)
    if f is None:
        return None  # pragma: no cover - caller checks field existence before calling
    return _unwrap_optional(f.annotation)


# ---------------------------------------------------------------------------
# Chain validation
# ---------------------------------------------------------------------------


def _validate_chain(
    chain: str,
    ctx_type: type[BaseModel],
    template: str,
) -> LintIssue | None:
    """Walk *chain* through *ctx_type* level by level.

    Returns a :class:`LintIssue` for the first segment that cannot be
    resolved, or ``None`` when the entire chain is valid.  Validation stops
    (without error) when it reaches a field whose type is not a Pydantic
    model — deeper access is opaque and left to the trial render.
    """
    parts = chain.split('.')
    current: object = ctx_type
    for i, part in enumerate(parts):
        if not (isinstance(current, type) and issubclass(current, BaseModel)):
            # Non-Pydantic type - cannot introspect further; not an error
            break
        if part not in current.model_fields:
            partial = '.'.join(parts[: i + 1])
            return LintIssue(
                template=template,
                chain=chain,
                reason=f"'{partial}' not found in {current.__name__}",
            )
        current = _field_type(current, part)
    return None


# ---------------------------------------------------------------------------
# Chain checking helper — extracted to keep _lint_template under complexity limit
# ---------------------------------------------------------------------------


def _check_chains(
    chains: set[str],
    ctx_dict: dict[str, object],
    ctx_type: type[BaseModel],
    template: str,
) -> list[LintIssue]:
    """Return issues for all access chains that cannot be resolved in *ctx_dict*."""
    issues: list[LintIssue] = []
    for chain in sorted(chains):
        root = chain.split('.')[0]
        if root not in ctx_dict:
            issues.append(
                LintIssue(
                    template=template,
                    chain=chain,
                    reason=f"'{root}' not in context",
                ),
            )
            continue
        issue = _validate_chain(chain, ctx_type, template)
        if issue is not None:
            issues.append(issue)
    return issues


# ---------------------------------------------------------------------------
# Per-template lint
# ---------------------------------------------------------------------------


def _lint_template(
    tpl_path: Path,
    tpl_root: Path,
    ctx_type: type[BaseModel],
    ctx_dict: dict[str, object],
    env: jinja2.Environment,
) -> TemplateResult:
    """Analyse *tpl_path* and return all issues plus a trial-render result."""
    rel = tpl_path.relative_to(tpl_root).as_posix()
    raw = tpl_path.read_text(encoding='utf-8')
    # Strip preprocessor directives so Jinja2 can parse clean source.
    # Pass empty local content — anchors keep their template defaults.
    cleaned = replace_text(raw, '')

    result = TemplateResult(path=rel)

    try:
        ast = env.parse(cleaned)
    except jinja2.TemplateSyntaxError as exc:
        result.render_error = f'syntax error: {exc}'
        return result

    # find_undeclared_variables handles scope (loop vars, set vars, etc.)
    undeclared: set[str] = jinja2.meta.find_undeclared_variables(ast)
    all_chains = _collect_chains(ast)
    external_chains = {c for c in all_chains if c.split('.')[0] in undeclared}
    result.issues.extend(
        _check_chains(
            _maximal_chains(external_chains),
            ctx_dict,
            ctx_type,
            rel,
        ),
    )

    # Trial render — catches dynamic errors the static pass cannot see
    try:
        env.from_string(cleaned).render(ctx_dict)
    except jinja2.UndefinedError as exc:
        result.render_error = str(exc)
    except Exception as exc:  # noqa: BLE001 - surface any render failure
        result.render_error = f'render error: {exc}'

    return result


# ---------------------------------------------------------------------------
# Command helpers — extracted to keep `command` under complexity limits
# ---------------------------------------------------------------------------


def _resolve_context(
    providers: SessionBundle,
    pid: str,
) -> tuple[dict[str, object], type[BaseModel]]:
    """Extract context dict and concrete type from the loaded providers object.

    The loader guarantees that every pid in module_cache has an entry in
    provider_contexts after finalize_provider_contexts runs, so ctx is always
    a BaseContext instance here.
    """
    ctx = providers.provider_contexts[pid]
    return ctx.model_dump(), type(ctx)


def _report_results(
    results: list[TemplateResult],
    console: Console,
) -> tuple[int, int]:
    """Print per-template results and return ``(issues_total, render_errors_total)``."""
    issues_total = 0
    render_errors_total = 0
    for r in results:
        if r.ok:
            console.print(f'[green]✓[/green] {r.path}')
            continue
        console.print(f'[red]✗[/red] {r.path}')
        for issue in r.issues:
            console.print(
                f'  [yellow]•[/yellow] [bold]{issue.chain}[/bold]: {issue.reason}',
            )
            issues_total += 1
        if r.render_error:
            console.print(f'  [red]render:[/red] {r.render_error}')
            render_errors_total += 1
    return issues_total, render_errors_total


# ---------------------------------------------------------------------------
# Command entry point
# ---------------------------------------------------------------------------


def command(provider_dir: Path) -> int:
    """Lint a provider's templates against its context model.

    Args:
        provider_dir: Root directory containing ``repolish.py`` and the
            ``repolish/`` template tree.

    Returns:
        0 when all templates are clean, 1 when any issue is found.
    """
    provider_dir = provider_dir.resolve()
    tpl_root = provider_dir / 'repolish'

    if not (provider_dir / 'repolish.py').exists():
        console.print(f'[red]No repolish.py found in {provider_dir}[/red]')
        logger.error(
            'provider_script_missing',
            path=str(provider_dir / 'repolish.py'),
        )
        return 1

    if not tpl_root.is_dir():
        console.print(
            f'[red]No repolish/ template directory found in {provider_dir}[/red]',
        )
        logger.error('templates_dir_missing', path=str(tpl_root))
        return 1

    console.rule('[bold]repolish lint')

    # Load provider and get finalized context (no inputs - single-provider run)
    try:
        providers = create_providers([str(provider_dir)])
        pid = provider_dir.as_posix()
        ctx_dict, ctx_type = _resolve_context(providers, pid)
    except RuntimeError as exc:
        console.print(f'[red]Failed to load provider: {exc}[/red]')
        logger.warning(
            'provider_load_failed',
            path=str(provider_dir),
            error=str(exc),
        )
        return 1

    logger.info(
        'lint_context_loaded',
        ctx_type=ctx_type.__name__,
        keys=list(ctx_dict.keys()),
    )

    env = jinja2.Environment(
        autoescape=select_autoescape(['html', 'xml'], default_for_string=False),
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
    )

    templates = sorted(f for f in tpl_root.rglob('*') if f.is_file())
    results = [_lint_template(tpl, tpl_root, ctx_type, ctx_dict, env) for tpl in templates]
    lint_result = LintResult(template_results=results)
    issues_total, render_errors_total = _report_results(results, console)

    console.print()
    if lint_result.ok:
        console.rule('[bold green]All templates OK[/bold green]')
        logger.info('lint_passed', templates=len(results))
        return 0

    console.rule('[bold red]Lint failed[/bold red]')
    logger.warning(
        'lint_failed',
        issues=issues_total,
        render_errors=render_errors_total,
    )
    return 1
