from pathlib import Path

from rich.console import Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from repolish.commands.apply.debug import debug_file_slug, _file_context_slug
from repolish.commands.apply.options import ResolvedSession
from repolish.config import ProviderSymlink
from repolish.console import console
from repolish.providers.models import (
    BaseContext,
    FileMode,
    FileRecord,
    SessionBundle,
)
from repolish.version import __version__


def print_startup() -> None:
    """Print the repolish startup banner."""
    console.print(f'[bold cyan]repolish[/bold cyan] [dim]v{__version__}[/dim]')


_MODE_STYLE: dict[str, str] = {
    'regular': 'green',
    'create_only': 'yellow',
    'delete': 'red',
    'keep': 'cyan',
}


def note_running_from_member(config_dir: Path, root: Path, rel: Path) -> None:
    """Print an informational note when `apply` runs standalone from a member directory.

    Running from a member is allowed — the member's own providers and templates
    apply correctly.  The root session is simply skipped, so root-managed files
    are not updated in this pass.

    Args:
        config_dir: The current working directory (member path).
        root: The detected monorepo root directory.
        rel: The member path relative to the monorepo root.
    """
    msg = (
        '[dim]note:[/] running standalone from member directory (root pass skipped)\n'
        f'  [dim]{config_dir}[/] is a member of [dim]{root}[/]\n'
        f'  for a full monorepo run: [bold]repolish apply --member {rel}[/] from the root'
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
        if not source and record.overlay_dir:
            source = f'{record.overlay_dir}/'
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
    debug_link = Text()
    debug_link.append(
        debug_file.name,
        style=f'link file://{debug_file.absolute()}',
    )
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


def _file_skip_reason(
    record: FileRecord,
    session: ResolvedSession,
) -> str | None:
    """Return why a file was not applied, or None if it was applied.

    Checks in order: suppressed template, paused file, then auto-staging
    disabled for a root monorepo pass (files not in ``create_file_mappings``
    are never written to the root).
    """
    if record.mode == FileMode.SUPPRESS:
        return 'suppressed'
    if record.path in frozenset(session.config.paused_files):
        return 'paused'
    if session.global_context.workspace.mode == 'root':
        if record.mode not in (
            FileMode.DELETE,
            FileMode.KEEP,
            FileMode.SUPPRESS,
        ):
            if record.path not in session.providers.file_mappings:
                return 'not in create_file_mappings (root mode)'
    return None


def _build_summary_tree(session: ResolvedSession) -> Tree:
    """Build a Tree summarising providers grouped by role with per-file status."""
    debug_dir = session.config.config_dir / '.repolish' / '_'
    records_by_owner: dict[str, list[FileRecord]] = {}
    for record in session.providers.file_records:
        records_by_owner.setdefault(record.owner, []).append(record)

    def _provider_label(
        alias: str,
        records: list[FileRecord],
        syms: list[ProviderSymlink],
    ) -> Text:
        skipped = sum(1 for r in records if _file_skip_reason(r, session) is not None)
        total = len(records) + len(syms)
        applied = total - skipped
        pid = session.alias_to_pid.get(alias)
        ctx = session.providers.provider_contexts.get(pid) if pid else None
        slug = debug_file_slug(ctx, alias)
        debug_file = debug_dir / f'provider-context.{slug}.json'
        label = Text()
        label.append(alias, style=f'bold link file://{debug_file.absolute()}')
        if skipped:
            label.append(
                f' [{applied} applied, {skipped} not applied]',
                style='dim yellow',
            )
        else:
            noun = 'file' if total == 1 else 'files'
            label.append(f' [{total} {noun}]', style='dim')
        return label

    def _file_node(record: FileRecord) -> Text:
        reason = _file_skip_reason(record, session)
        file_ctx_file = debug_dir / 'file-ctx' / f'file-context.{_file_context_slug(record.path)}.json'
        node = Text()
        if reason:
            node.append('✗ ', style='yellow')
            node.append(record.path)
            node.append(f'  {reason}', style='dim yellow')
        else:
            node.append('✓ ', style='green')
            link = (
                f'link file://{file_ctx_file.absolute()}'
                if record.mode in (FileMode.REGULAR, FileMode.CREATE_ONLY)
                else ''
            )
            node.append(record.path, style=link)
            mode_val = record.mode.value
            if mode_val != 'regular':
                style = _MODE_STYLE.get(mode_val, '')
                node.append(f'  {mode_val}', style=f'dim {style}'.strip())
        return node

    def _symlink_node(sl: ProviderSymlink) -> Text:
        node = Text()
        node.append('\u2197 ', style='blue')
        node.append(str(sl.target))
        node.append(f'  \u2192 {sl.source}', style='dim')
        return node

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

    def _add_provider(group_branch: Tree, alias: str) -> None:
        records = records_by_owner.get(alias, [])
        syms = session.resolved_symlinks.get(alias, [])
        provider_node = group_branch.add(_provider_label(alias, records, syms))
        for record in records:
            provider_node.add(_file_node(record))
        for sl in syms:
            provider_node.add(_symlink_node(sl))

    tree = Tree('[bold]apply summary[/bold]')
    if root_aliases:
        branch = tree.add('[bold]Root[/bold]')
        for alias in root_aliases:
            _add_provider(branch, alias)
    for member_name, m_aliases in member_aliases.items():
        branch = tree.add(f'[bold]Member: {member_name}[/bold]')
        for alias in m_aliases:
            _add_provider(branch, alias)
    if standalone_aliases:
        branch = tree.add('[bold]Standalone[/bold]')
        for alias in standalone_aliases:
            _add_provider(branch, alias)
    return tree


def log_providers_summary(session: ResolvedSession) -> None:
    """Print provider panels for one session."""
    _print_provider_panels(session)


def print_summary_tree(sessions: list[ResolvedSession]) -> None:
    """Print a combined Tree summary across all sessions."""
    # Merge all sessions into a single tree rooted at 'apply summary'.
    # Each session contributes its groups (Root / Member / Standalone).
    # When there is only one session the groups are added directly.
    tree = Tree('[bold]apply summary[/bold]')
    if len(sessions) == 1:
        sub = _build_summary_tree(sessions[0])
        for branch in sub.children:
            tree.add(branch)
    else:
        for session in sessions:
            sub = _build_summary_tree(session)
            for branch in sub.children:
                tree.add(branch)
    console.print(tree)
