from pathlib import Path

from hotlog import get_logger
from rich.console import Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from repolish.commands.apply.debug import debug_file_slug
from repolish.commands.apply.options import ResolvedSession
from repolish.config import ProviderSymlink
from repolish.console import console
from repolish.providers.models import (
    BaseContext,
    SessionBundle,
)

logger = get_logger(__name__)

_MODE_STYLE: dict[str, str] = {
    'regular': 'green',
    'create_only': 'yellow',
    'delete': 'red',
    'keep': 'cyan',
}


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


def _role_label(ctx: object) -> str:
    """Return a display label for the provider's monorepo role."""
    try:
        if isinstance(ctx, BaseContext):
            info = ctx.repolish.provider.session
            if info.mode == 'root':
                return 'root'
            if info.mode == 'member' and info.member_name:
                return f'member: {info.member_name}'
    except Exception:  # noqa: BLE001
        pass
    return 'standalone'


def _build_provider_table(
    owner: str,
    records: list,
    owner_symlinks: list[ProviderSymlink],
) -> Table:
    """Build a Rich Table for one provider showing files and symlinks."""
    total = len(records) + len(owner_symlinks)
    title = f'{owner} ({total} file{"s" if total != 1 else ""})'
    table = Table(title=title, show_header=True, header_style='bold')
    table.add_column('Mode', style='dim', no_wrap=True)
    table.add_column('Path')
    table.add_column('Source', style='dim')
    for record in records:
        mode_val = record.mode.value
        style = _MODE_STYLE.get(mode_val, '')
        source = record.source if record.source and record.source != record.path else ''
        table.add_row(f'[{style}]{mode_val}[/{style}]', record.path, source)
    for sl in owner_symlinks:
        table.add_row('[blue]symlink[/blue]', str(sl.target), str(sl.source))
    return table


def print_files_summary(
    providers: SessionBundle,
    symlinks: dict[str, list[ProviderSymlink]] | None = None,
) -> None:
    """Print one Rich table per provider alias showing mode and path for each file."""
    by_owner: dict[str, list] = {}
    for record in providers.file_records:
        by_owner.setdefault(record.owner, []).append(record)

    _syms = symlinks if symlinks is not None else {}
    all_owners = list(by_owner.keys())
    for alias in _syms:
        if alias not in all_owners:
            all_owners.append(alias)

    for owner in all_owners:
        console.print(
            _build_provider_table(
                owner,
                by_owner.get(owner, []),
                _syms.get(owner, []),
            ),
        )


def _build_provider_panel(session: ResolvedSession, alias: str) -> Panel:
    """Build a Rich Panel for one provider with property, context, and files sections."""
    pid = session.alias_to_pid.get(alias)
    ctx = session.providers.provider_contexts.get(pid) if pid else None
    records = [r for r in session.providers.file_records if r.owner == alias]
    owner_symlinks = session.resolved_symlinks.get(alias, [])
    role = _role_label(ctx)
    props = Table.grid(padding=(0, 1))
    props.add_column(style='bold cyan', no_wrap=True)
    props.add_column(overflow='fold')
    debug_dir = session.config.config_dir / '.repolish' / '_'
    slug = debug_file_slug(ctx, alias)
    debug_file = debug_dir / f'provider-context.{slug}.json'
    root_dir = session.global_context.workspace.root_dir
    try:
        debug_link = str(debug_file.relative_to(root_dir))
    except ValueError:
        debug_link = str(debug_file)
    props.add_row('alias', alias)
    props.add_row('role', role)
    if ctx is not None and isinstance(ctx, BaseContext):
        info = ctx.repolish.provider
        props.add_row('project', info.project_name)
        props.add_row('package', info.package_name)
        props.add_row('version', info.version)
    props.add_row('debug', debug_link)

    total = len(records) + len(owner_symlinks)
    if total:
        files_table = Table(
            show_header=True,
            header_style='bold',
            box=None,
            padding=(0, 1),
        )
        files_table.add_column('Mode', style='dim', no_wrap=True)
        files_table.add_column('Path')
        files_table.add_column('Source', style='dim')
        for record in records:
            mode_val = record.mode.value
            style = _MODE_STYLE.get(mode_val, '')
            source = record.source if record.source and record.source != record.path else ''
            files_table.add_row(
                f'[{style}]{mode_val}[/{style}]',
                record.path,
                source,
            )
        for sl in owner_symlinks:
            files_table.add_row(
                '[blue]symlink[/blue]',
                str(sl.target),
                str(sl.source),
            )
    else:
        files_table = Text('(no files)', style='dim')

    body = Group(
        props,
        Rule(style='dim'),
        Text(f'files ({total})', style='bold'),
        files_table,
    )
    return Panel(body, title=f'[bold]{alias}[/bold]', border_style='cyan')


def _print_provider_panels(session: ResolvedSession) -> None:
    """Print Rich panels for all providers, grouped by monorepo role."""
    root_aliases: list[str] = []
    member_aliases: dict[str, list[str]] = {}
    standalone_aliases: list[str] = []

    for alias in session.aliases:
        pid = session.alias_to_pid.get(alias)
        ctx = session.providers.provider_contexts.get(pid) if pid else None
        label = _role_label(ctx)
        if label == 'root':
            root_aliases.append(alias)
        elif label.startswith('member:'):
            member_name = label[len('member: ') :]
            member_aliases.setdefault(member_name, []).append(alias)
        else:
            standalone_aliases.append(alias)

    def _emit(group_title: str, group_aliases: list[str]) -> None:
        console.print(Rule(f'[bold]{group_title}[/bold]', style='bright_black'))
        for a in group_aliases:
            console.print(_build_provider_panel(session, a))

    if root_aliases:
        _emit('Root', root_aliases)
    for member_name, m_aliases in member_aliases.items():
        _emit(f'Member: {member_name}', m_aliases)
    if standalone_aliases:
        _emit('Standalone', standalone_aliases)


def log_providers_summary(session: ResolvedSession) -> None:
    """Print provider panels and log the location of the debug output directory."""
    _print_provider_panels(session)
    debug_dir = session.config.config_dir / '.repolish' / '_'
    logger.info(
        'providers_ready',
        debug_dir=str(debug_dir),
        suggestion='see debug_dir for per-provider context and file decisions',
    )
