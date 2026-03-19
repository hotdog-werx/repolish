from dataclasses import dataclass
from pathlib import Path

from hotlog import get_logger
from repolish.commands.apply.symlinks import check_symlinks
from repolish.config import ResolvedProviderInfo
from repolish.hydration import check_generated_output, render_template, rich_print_diffs
from repolish.loader.models import Providers

logger = get_logger(__name__)


@dataclass
class CheckContext:
    """Groups the parameters needed to run a check-only session."""

    setup_output: Path
    providers: Providers
    base_dir: Path
    paused: frozenset[str]
    resolved_symlinks: dict[str, list]
    provider_infos: dict[str, ResolvedProviderInfo]
    disable_auto_staging: bool = False


def _render_templates(
    setup_input: Path,
    providers: Providers,
    setup_output: Path,
) -> int:
    """Render templates; return 1 on error, 0 on success."""
    try:
        render_template(setup_input, providers, setup_output)
    except RuntimeError as exc:
        errors = [line for line in str(exc).splitlines() if line and not line.endswith(':')]
        logger.exception('render_failed', errors=errors)
        return 1
    return 0


def _finish_check(ctx: CheckContext) -> int:
    """Run check mode: report diffs and symlink issues; return 2 if any, else 0."""
    diffs = check_generated_output(
        ctx.setup_output,
        ctx.providers,
        ctx.base_dir,
        paused_files=ctx.paused,
        disable_auto_staging=ctx.disable_auto_staging,
    )
    symlink_issues = check_symlinks(ctx.resolved_symlinks, ctx.provider_infos)
    if diffs:
        logger.error(
            'check_results',
            suggestion='run `repolish apply` to apply changes',
        )
        rich_print_diffs(diffs)
    if symlink_issues:
        logger.error(
            'symlink_check_failed',
            issues=symlink_issues,
            suggestion='run `repolish apply` to fix symlinks',
        )
    return 2 if (diffs or symlink_issues) else 0
