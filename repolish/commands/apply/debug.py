import json
from pathlib import Path

from pydantic import BaseModel

from repolish.commands.apply.pipeline import _ordered_aliases
from repolish.config import RepolishConfig
from repolish.misc import ctx_to_dict
from repolish.providers._log import logger
from repolish.providers.models import SessionBundle, TemplateMapping


def _to_jsonable(value: object) -> object:
    """Recursively convert a value to a JSON-serializable structure.

    Handles Pydantic models (via ``model_dump``), dicts, lists, tuples,
    sets/frozensets (converted to sorted lists), and primitives.
    Any other type is passed through as-is for ``json.dumps`` to handle.
    """
    # pragma: no cover — ctx_to_dict calls model_dump() before _to_jsonable is
    # invoked, so no BaseModel instances survive into the recursive calls
    if isinstance(value, BaseModel):  # pragma: no cover
        return _to_jsonable(value.model_dump())
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    # pragma: no cover — Pydantic model_dump() serialises set/frozenset fields
    # to plain lists before _to_jsonable is called, so this branch is never
    # reached in practice; retained for correctness if callers evolve.
    if isinstance(value, (set, frozenset)):  # pragma: no cover
        return [_to_jsonable(item) for item in value]
    return value


def collect_provider_files(
    providers: SessionBundle,
    alias: str,
) -> list[dict[str, str | None]]:
    """Return sorted list of {path, mode, source} for files this provider contributes."""
    return [
        {'path': r.path, 'mode': r.mode.value, 'source': r.source} for r in providers.file_records if r.owner == alias
    ]


def debug_file_slug(ctx: object, alias: str) -> str:
    """Return a filename slug capturing session role + provider alias.

    Examples::

        root.devkit-workspace
        pkg-alpha.devkit-python
        standalone.simple-provider
    """
    try:
        from repolish.providers.models import BaseContext  # noqa: PLC0415

        if isinstance(ctx, BaseContext):
            info = ctx.repolish.provider
            mode = info.session.mode
            if mode == 'root':
                prefix = 'root'
            elif mode == 'member' and info.session.member_name:
                prefix = info.session.member_name
            else:
                prefix = 'standalone'
            return f'{prefix}.{alias}'
    except Exception as exc:  # noqa: BLE001  # pragma: no cover — defensive fallback; only reachable if BaseContext internals diverge after a refactor, not expected in production
        logger.warning(
            'debug_file_slug_exception',
            error=str(exc),
            ctx_type=type(ctx).__name__,
            alias=alias,
        )
    return f'standalone.{alias}'


def write_provider_debug_files(
    base_dir: Path,
    config: RepolishConfig,
    providers: SessionBundle,
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
        slug = debug_file_slug(ctx, alias)
        data: dict[str, object] = {
            'alias': alias,
            'context': ctx_to_dict(ctx),
            'files': collect_provider_files(providers, alias),
        }
        out_path = debug_dir / f'provider-context.{slug}.json'
        out_path.write_text(
            json.dumps(_to_jsonable(data), indent=2),
            encoding='utf-8',
        )


def _file_context_slug(dest_path: str) -> str:
    """Convert a destination path to a debug filename slug.

    Replaces ``/`` with ``--`` so nested paths remain readable as filenames::

        'root_file.md'        → 'root_file.md'
        'some/nested/file.md' → 'some--nested--file.md'
    """
    return dest_path.replace('/', '--')


def write_file_context_debug_files(
    base_dir: Path,
    providers: SessionBundle,
    alias_to_pid: dict[str, str],
) -> None:
    """Write per-rendered-file context debug files to ``.repolish/_/``.

    Each file rendered from a template gets a
    ``file-context.<dest-slug>.json`` file that records what context was
    available during rendering, including any ``extra_context`` injected via
    a :class:`TemplateMapping`.  A ``provider_context_file`` key links to the
    corresponding ``provider-context.*.json`` file for cross-reference.

    Only ``REGULAR`` and ``CREATE_ONLY`` files are written; ``DELETE``,
    ``KEEP``, and ``SUPPRESS`` entries are skipped because they are not
    rendered.
    """
    from repolish.providers.models.files import FileMode  # noqa: PLC0415

    debug_dir = base_dir / '.repolish' / '_'
    debug_dir.mkdir(parents=True, exist_ok=True)
    file_ctx_dir = debug_dir / 'file-ctx'
    file_ctx_dir.mkdir(parents=True, exist_ok=True)

    for record in providers.file_records:
        if record.mode not in (FileMode.REGULAR, FileMode.CREATE_ONLY):
            continue

        dest = record.path
        alias = record.owner
        pid = alias_to_pid.get(alias)
        ctx = providers.provider_contexts.get(pid) if pid else None
        provider_ctx_file = f'provider-context.{debug_file_slug(ctx, alias)}.json'

        mapping = providers.file_mappings.get(dest)
        extra: object = (
            mapping.extra_context
            if isinstance(mapping, TemplateMapping) and mapping.extra_context is not None
            else None
        )

        data: dict[str, object] = {
            'dest': dest,
            'owner': alias,
            'source_template': record.source,
            'provider_context_file': provider_ctx_file,
            'extra_context': _to_jsonable(extra) if extra is not None else {},
        }
        out_path = debug_dir / 'file-ctx' / f'file-context.{_file_context_slug(dest)}.json'
        out_path.write_text(
            json.dumps(_to_jsonable(data), indent=2),
            encoding='utf-8',
        )
