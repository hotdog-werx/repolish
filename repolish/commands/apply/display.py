from pathlib import Path

from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from repolish.commands.apply.debug import _file_context_slug, debug_file_slug
from repolish.commands.apply.options import ResolvedSession
from repolish.config import ProviderSymlink
from repolish.console import console, supports_hyperlinks
from repolish.providers._log import logger
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

# (prefix, prefix_style) keyed by apply_result status; default → written
_FILE_STATUS_PREFIX: dict[str | None, tuple[str, str]] = {
    'unchanged': ('~ ', 'dim cyan'),
    'deleted': ('✗ ', 'dim red'),
    'drift': ('✗ ', 'red'),
}

# (prefix, prefix_style, annotation_fmt, annotation_style) keyed by promoted status
_PROMO_STATUS_FMT: dict[str | None, tuple[str, str, str, str]] = {
    'overridden_by_root': (
        '↑ ',
        'dim yellow',
        '  ⚠ overridden by {owner}',
        'dim yellow',
    ),
    'unchanged': ('~ ', 'dim cyan', '  ↑ promoted from {from_}', 'dim'),
    'differs': (
        '↑ ',
        'yellow',
        '  promoted from {from_} (differs)',
        'dim yellow',
    ),
}
_PROMO_DEFAULT_FMT: tuple[str, str, str, str] = (
    '↑ ',
    'green',
    '  promoted from {from_}',
    'dim',
)


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
    except Exception as exc:  # noqa: BLE001  # pragma: no cover — defensive: BaseContext.repolish is always valid; only a deeply broken ctx object would trigger this
        logger.warning(  # pragma: no cover
            'role_label_exception',
            error=str(exc),
            ctx_type=type(ctx).__name__,
        )
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
    if (
        session.global_context.workspace.mode == 'root'
        and record.mode
        not in (
            FileMode.DELETE,
            FileMode.KEEP,
            FileMode.SUPPRESS,
        )
        and record.path not in session.providers.file_mappings
    ):
        return 'not in create_file_mappings (root mode)'
    return None


def _symlink_node(sl: ProviderSymlink) -> Text:
    node = Text()
    node.append('↗ ', style='blue')
    node.append(str(sl.target))
    node.append(f'  → {sl.source}', style='dim')
    return node


def _promoted_file_node(
    record: FileRecord,
    promoted_apply_result: dict[str, str],
) -> Text:
    node = Text()
    promo_status = promoted_apply_result.get(record.path) if promoted_apply_result else None
    prefix, pfx_style, annot_fmt, annot_style = _PROMO_STATUS_FMT.get(
        promo_status,
        _PROMO_DEFAULT_FMT,
    )
    node.append(prefix, style=pfx_style)
    node.append(record.path)
    node.append(
        annot_fmt.format(
            owner=record.overridden_by or 'root',
            from_=record.promoted_from,
        ),
        style=annot_style,
    )
    return node


def _file_node(
    record: FileRecord,
    session: ResolvedSession,
    debug_dir: Path,
) -> Text:
    reason = _file_skip_reason(record, session)
    file_ctx_file = debug_dir / 'file-ctx' / f'file-context.{_file_context_slug(record.path)}.json'
    node = Text()
    if reason:
        node.append('✗ ', style='yellow')
        node.append(record.path)
        node.append(f'  {reason}', style='dim yellow')
        return node
    file_status = session.apply_result.get(record.path) if session.apply_result else None
    prefix, pfx_style = _FILE_STATUS_PREFIX.get(file_status, ('✓ ', 'green'))
    node.append(prefix, style=pfx_style)
    link = (
        f'link file://{file_ctx_file.absolute()}'
        if supports_hyperlinks and record.mode in (FileMode.REGULAR, FileMode.CREATE_ONLY)
        else ''
    )
    node.append(record.path, style=link)
    mode_val = record.mode.value
    if mode_val not in ('regular', 'delete'):
        style = _MODE_STYLE.get(mode_val, '')
        node.append(f'  {mode_val}', style=f'dim {style}'.strip())
    source = record.source if record.source and record.source != record.path else ''
    if not source and record.overlay_dir:
        source = f'{record.overlay_dir}/'
    if source:
        node.append(f'  ← {source}', style='dim')
    return node


def _append_stat_parts(label: Text, parts: list[str]) -> None:
    """Append formatted stat parts to *label* separated by dim · dots."""
    label.append('  ')
    for i, part in enumerate(parts):
        if i:
            label.append(' · ', style='dim')
        label.append_text(Text.from_markup(part))


def _append_applied_stats(
    label: Text,
    records: list[FileRecord],
    syms: list[ProviderSymlink],
    session: ResolvedSession,
) -> None:
    """Append post-apply counts (written/unchanged/deleted/skipped/symlinks) to *label*."""
    record_paths = {r.path for r in records}
    written = sum(1 for p in record_paths if session.apply_result.get(p) == 'written')
    unchanged = sum(1 for p in record_paths if session.apply_result.get(p) == 'unchanged')
    deleted = sum(1 for p in record_paths if session.apply_result.get(p) == 'deleted')
    drift = sum(1 for p in record_paths if session.apply_result.get(p) == 'drift')
    skipped = sum(1 for r in records if _file_skip_reason(r, session) is not None)
    stat_items = [
        (written, '[green]{n} written[/green]'),
        (unchanged, '[dim]{n} unchanged[/dim]'),
        (deleted, '[dim red]{n} deleted[/dim red]'),
        (drift, '[red]{n} drift[/red]'),
        (skipped, '[yellow]{n} skipped[/yellow]'),
        (len(syms), '[blue]{n} symlinks[/blue]'),
    ]
    parts = [fmt.format(n=n) for n, fmt in stat_items if n]
    if parts:
        _append_stat_parts(label, parts)


def _append_pending_count(
    label: Text,
    records: list[FileRecord],
    syms: list[ProviderSymlink],
    session: ResolvedSession,
) -> None:
    """Append a simple applied/not-applied count to *label* (pre-apply display)."""
    skipped = sum(1 for r in records if _file_skip_reason(r, session) is not None)
    total = len(records) + len(syms)
    applied = total - skipped
    if skipped:
        label.append(
            f'  [{applied} applied, {skipped} not applied]',
            style='dim yellow',
        )
    else:
        noun = 'file' if total == 1 else 'files'
        label.append(f'  [{total} {noun}]', style='dim')


def _append_provider_stat_suffix(
    label: Text,
    records: list[FileRecord],
    syms: list[ProviderSymlink],
    session: ResolvedSession,
) -> None:
    """Append a compact file-count stats suffix to *label* in-place."""
    if session.apply_result:
        _append_applied_stats(label, records, syms, session)
    else:
        _append_pending_count(label, records, syms, session)


def _provider_label(
    alias: str,
    records: list[FileRecord],
    syms: list[ProviderSymlink],
    session: ResolvedSession,
    debug_dir: Path,
) -> Text:
    pid = session.alias_to_pid.get(alias)
    ctx = session.providers.provider_contexts.get(pid) if pid else None
    slug = debug_file_slug(ctx, alias)
    debug_file = debug_dir / f'provider-context.{slug}.json'
    label = Text()
    label.append(
        alias,
        style=f'bold link file://{debug_file.absolute()}' if supports_hyperlinks else 'bold',
    )
    if ctx is not None and isinstance(ctx, BaseContext):
        label.append(f'@{ctx.repolish.provider.version}', style='dim')
    _append_provider_stat_suffix(label, records, syms, session)
    return label


def _add_provider_branch(
    group_branch: Tree,
    alias: str,
    records_by_owner: dict[str, list[FileRecord]],
    session: ResolvedSession,
    debug_dir: Path,
) -> None:
    records = records_by_owner.get(alias, [])
    syms = session.resolved_symlinks.get(alias, [])
    provider_node = group_branch.add(
        _provider_label(alias, records, syms, session, debug_dir),
    )
    for record in records:
        provider_node.add(_file_node(record, session, debug_dir))
    for sl in syms:
        provider_node.add(_symlink_node(sl))


def _classify_aliases(
    session: ResolvedSession,
) -> tuple[list[str], dict[str, list[str]], list[str]]:
    """Split session aliases into root, per-member, and standalone groups."""
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
    return root_aliases, member_aliases, standalone_aliases


def _add_root_branch_to_tree(
    tree: Tree,
    root_aliases: list[str],
    records_by_owner: dict[str, list[FileRecord]],
    session: ResolvedSession,
    debug_dir: Path,
) -> None:
    """Add a Root branch (with promoted-file sub-branch) to *tree* when applicable."""
    if not root_aliases:
        return
    branch = tree.add('[bold]Root[/bold]')
    for alias in root_aliases:
        _add_provider_branch(
            branch,
            alias,
            records_by_owner,
            session,
            debug_dir,
        )
    if session.promoted_records:
        promo_branch = branch.add('[bold]Promoted[/bold]')
        for record in session.promoted_records:
            promo_branch.add(
                _promoted_file_node(record, session.promoted_apply_result),
            )


def _build_summary_tree(session: ResolvedSession) -> Tree:
    """Build a Tree summarising providers grouped by role with per-file status."""
    debug_dir = session.config.config_dir / '.repolish' / '_'
    records_by_owner: dict[str, list[FileRecord]] = {}
    for record in session.providers.file_records:
        records_by_owner.setdefault(record.owner, []).append(record)

    root_aliases, member_aliases, standalone_aliases = _classify_aliases(
        session,
    )

    tree = Tree('[bold]apply summary[/bold]')
    _add_root_branch_to_tree(
        tree,
        root_aliases,
        records_by_owner,
        session,
        debug_dir,
    )
    for member_name, m_aliases in member_aliases.items():
        branch = tree.add(f'[bold]Member: {member_name}[/bold]')
        for alias in m_aliases:
            _add_provider_branch(
                branch,
                alias,
                records_by_owner,
                session,
                debug_dir,
            )
    if standalone_aliases:
        branch = tree.add('[bold]Standalone[/bold]')
        for alias in standalone_aliases:
            _add_provider_branch(
                branch,
                alias,
                records_by_owner,
                session,
                debug_dir,
            )
    return tree


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
