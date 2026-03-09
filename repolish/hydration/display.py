from rich.console import Console
from rich.syntax import Syntax


def rich_print_diffs(
    diffs: list[tuple[str, str]],
    console: Console | None = None,
) -> None:
    """Print diffs using rich formatting.

    Args:
        diffs: List of tuples (relative_path, message_or_unified_diff)
        console: Optional Rich Console instance.  Defaults to a
            ``force_terminal=True`` console so colours appear in CI.
    """
    if console is None:
        console = Console(force_terminal=True)  # Enable colors in CI
    for rel, msg in diffs:
        console.rule(f'[bold]{rel}')
        if msg in ('MISSING', 'PRESENT_BUT_SHOULD_BE_DELETED'):
            console.print(msg, soft_wrap=True)
        else:
            # highlight as a diff
            syntax = Syntax(msg, 'diff', theme='ansi_dark', word_wrap=False)
            console.print(syntax, soft_wrap=True)
