import json
from pathlib import Path

from repolish.commands.apply.pipeline import _ordered_aliases
from repolish.config import RepolishConfig
from repolish.loader.models import Providers
from repolish.misc import ctx_to_dict


def collect_provider_files(
    providers: Providers,
    alias: str,
) -> list[dict[str, str | None]]:
    """Return sorted list of {path, mode, source} for files this provider contributes."""
    return [
        {'path': r.path, 'mode': r.mode.value, 'source': r.source} for r in providers.file_records if r.owner == alias
    ]


def _debug_file_slug(ctx: object, alias: str) -> str:
    """Return a filename slug capturing monorepo role + provider alias.

    Examples::

        root.devkit-workspace
        pkg-alpha.devkit-python
        standalone.simple-provider
    """
    try:
        from repolish.loader.models import BaseContext  # noqa: PLC0415

        if isinstance(ctx, BaseContext):
            info = ctx._provider
            mode = info.monorepo.mode
            if mode == 'root':
                prefix = 'root'
            elif mode == 'package' and info.monorepo.member_name:
                prefix = info.monorepo.member_name
            else:
                prefix = 'standalone'
            return f'{prefix}.{alias}'
    except Exception:  # noqa: BLE001
        pass
    return f'standalone.{alias}'


def _write_provider_debug_files(
    base_dir: Path,
    config: RepolishConfig,
    providers: Providers,
    alias_to_pid: dict[str, str],
) -> None:
    """Write per-provider context and file decisions to .repolish/_/.

    Each provider gets a ``provider-context.<role>.<alias>.json`` file where
    ``role`` is ``root``, ``standalone``, or the member package name.
    Written after staging so ``template_sources`` is already populated.
    """
    debug_dir = base_dir / '.repolish' / '_'
    debug_dir.mkdir(parents=True, exist_ok=True)

    for alias in _ordered_aliases(config):
        pid = alias_to_pid.get(alias)
        if not pid:
            continue
        ctx = providers.provider_contexts.get(pid)
        slug = _debug_file_slug(ctx, alias)
        data: dict[str, object] = {
            'alias': alias,
            'context': ctx_to_dict(ctx),
            'files': collect_provider_files(providers, alias),
        }
        out_path = debug_dir / f'provider-context.{slug}.json'
        out_path.write_text(
            json.dumps(data, indent=2, default=str),
            encoding='utf-8',
        )
