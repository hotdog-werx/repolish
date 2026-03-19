from pathlib import Path

from repolish.console import console


def error_running_from_member(config_dir: Path, root: Path, rel: Path) -> None:
    """Display an error when `apply` is invoked from inside a monorepo member.

    When a user runs `repolish apply` from inside a member repository, the
    correct behavior is to run the command from the monorepo root (or to use
    `--standalone`). This helper prints a helpful, rich-formatted message
    describing the situation and offering next steps.

    Args:
        config_dir: The current working directory (member path).
        root: The detected monorepo root directory.
        rel: The member path relative to the monorepo root (for the suggested
            `--member` command).
    """
    msg = (
        '[bold red]error:[/] running from a monorepo member directory\n'
        f'  [dim]{config_dir}[/] is a member of the monorepo rooted at [dim]{root}[/]\n\n'
        '[bold yellow]hint:[/] run [bold]repolish apply[/] from the root, or target this member from the root:\n'
        f'      [bold]repolish apply --member {rel}[/]\n'
        '      pass [bold]--standalone[/] to bypass this check entirely'
    )
    console.print(msg)


def error_unknown_member(member: str, valid_names: list[str]) -> None:
    """Display an error when `--member` does not match any known member.

    Args:
        member: The member identifier passed on the command line.
        valid_names: The list of known member names that can be used instead.
    """
    valid_names_str = ', '.join(f'[bold]{n}[/]' for n in valid_names)
    msg = (
        f'[bold red]error:[/] unknown member [bold]{member!r}[/]\n\n'
        f'[bold yellow]hint:[/] valid members: {valid_names_str}'
    )
    console.print(msg)
