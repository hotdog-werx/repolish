"""Monorepo orchestration: dry passes, member data collection, and full multi-pass runs."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import TYPE_CHECKING

from repolish.commands.apply.options import MemberDryRunData
from repolish.config.loader import load_config_file
from repolish.config.topology import (
    detect_monorepo,
    detect_monorepo_from_config,
)
from repolish.loader.models import (
    BaseInputs,
    GlobalContext,
    ProviderEntry,
    get_global_context,
)
from repolish.loader.models.context import MemberInfo, MonorepoContext

if TYPE_CHECKING:
    from collections.abc import Iterator

    from repolish.config import RepolishConfig


@contextlib.contextmanager
def _chdir(path: Path) -> Iterator[None]:
    """Context manager that temporarily changes the working directory."""
    old = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(old)


def collect_member_data(
    members: list[MemberInfo],
    root_dir: Path,
    monorepo_ctx: MonorepoContext,
) -> list[MemberDryRunData]:
    """Run a dry provider pipeline for each member and collect ProviderEntry + emitted inputs.

    For each member:
    1. Changes the working directory to the member's directory.
    2. Loads its ``repolish.yaml`` via :func:`load_config_file`.
    3. Builds a ``GlobalContext`` with ``mode="package"`` for this member.
    4. Calls :func:`create_providers` in dry-run mode.
    5. Collects the :class:`DryRunResult` (entries + inputs).

    The ``MonorepoContext`` injected into each member's dry pass has
    ``mode="package"`` so providers know they are inside a package context even
    during the dry pass.
    """
    from repolish.config.resolution import resolve_config  # noqa: PLC0415
    from repolish.linker.health import ensure_providers_ready  # noqa: PLC0415
    from repolish.loader.orchestrator import create_providers  # noqa: PLC0415
    from repolish.loader.pipeline import DryRunResult  # noqa: PLC0415

    results: list[MemberDryRunData] = []

    for member in members:
        member_dir = (root_dir / member.path).resolve()
        member_config_path = member_dir / 'repolish.yaml'

        member_posix = member.path.as_posix()

        # Build a MonorepoContext for this individual package dry pass.
        pkg_mono_ctx = MonorepoContext(
            mode='package',
            root_dir=root_dir,
            package_dir=member_dir,
            members=monorepo_ctx.members,
        )
        member_global_ctx = _build_global_context(pkg_mono_ctx)

        with _chdir(member_dir):
            raw_cfg = load_config_file(member_config_path)
            aliases = raw_cfg.providers_order or list(raw_cfg.providers.keys())
            # Silently ensure providers are ready; failures are non-fatal for
            # the dry pass (the full member pass will surface them properly).
            ensure_providers_ready(
                aliases,
                raw_cfg.providers,
                member_dir,
                strict=False,
            )

            resolved = resolve_config(raw_cfg)
            _alias_to_pid = {alias: info.provider_root.as_posix() for alias, info in resolved.providers.items()}
            dirs: list[str | tuple[str, str]] = list(_alias_to_pid.items())

            provider_overrides = _build_provider_overrides(resolved)

            dry_result = create_providers(
                dirs,
                provider_overrides=provider_overrides,
                global_context=member_global_ctx,
                dry_run=True,
            )

        if not isinstance(dry_result, DryRunResult):
            # Should never happen when dry_run=True, but be defensive.
            results.append(MemberDryRunData(member_path=member_posix))
            continue

        results.append(
            MemberDryRunData(
                member_path=member_posix,
                provider_entries=dry_result.all_providers_list,
                emitted_inputs=dry_result.emitted_inputs,
            ),
        )

    return results


def _build_global_context(mono_ctx: MonorepoContext) -> GlobalContext:
    """Return a :class:`GlobalContext` with the given ``MonorepoContext`` injected."""
    base = get_global_context()
    return base.model_copy(update={'monorepo': mono_ctx})


def _build_provider_overrides(
    config: RepolishConfig,
) -> dict[str, dict[str, object]]:
    """Build the provider-override map used by ``create_providers``."""
    from repolish.misc import ctx_to_dict  # noqa: PLC0415

    overrides: dict[str, dict[str, object]] = {}
    for info in config.providers.values():
        pid = info.provider_root.as_posix()
        merged: dict[str, object] = {}
        if info.context:
            merged.update(ctx_to_dict(info.context))
        if info.context_overrides:
            merged.update(info.context_overrides)
        if merged:
            overrides[pid] = merged
    return overrides


def _run_project_session(  # noqa: PLR0913
    config_path: Path,
    mono_ctx: MonorepoContext,
    *,
    check_only: bool,
    strict: bool = False,
    extra_provider_entries: list[ProviderEntry] | None = None,
    extra_inputs: list[BaseInputs] | None = None,
) -> int:
    """Run a single full repolish pass in the directory of *config_path*.

    Injects *mono_ctx* into the ``GlobalContext`` so every provider's context
    carries ``repolish.monorepo``.  *extra_provider_entries* and *extra_inputs*
    are forwarded for member-to-root input routing (root pass only; ``None``
    for member passes).
    """
    from repolish.commands.apply import ApplyOptions  # noqa: PLC0415
    from repolish.commands.apply import run_session as apply_command

    config_dir = config_path.resolve().parent
    global_ctx = _build_global_context(mono_ctx)

    with _chdir(config_dir):
        return apply_command(
            ApplyOptions(
                config_path=config_path.resolve(),
                check_only=check_only,
                strict=strict,
                global_context=global_ctx,
                extra_provider_entries=extra_provider_entries,
                extra_inputs=extra_inputs,
            ),
        )


def coordinate_sessions(  # noqa: C901 - TODO: split into detect / dry-pass / root-pass / member-pass helpers
    config_path: Path,
    *,
    check_only: bool,
    strict: bool = False,
    member: str | None = None,
    root_only: bool = False,
) -> int:
    """Orchestrate a full monorepo repolish run.

    Flow:
    1. Detect monorepo topology (from ``repolish.yaml`` or ``pyproject.toml``).
    2. If not a monorepo, fall back to a single-pass :func:`apply_command`.
    3. Run a dry provider pipeline for every member to collect emitted inputs.
    4. Root pass (skipped when ``--member`` is given): inject member data.
    5. Member passes (skipped when ``--root-only``): isolated full passes.
    """
    from repolish.commands.apply import ApplyOptions  # noqa: PLC0415
    from repolish.commands.apply import run_session as apply_command

    config_dir = config_path.resolve().parent
    raw_config = load_config_file(config_path)

    if raw_config.monorepo and raw_config.monorepo.members:
        mono_ctx = detect_monorepo_from_config(config_dir, raw_config.monorepo)
    else:
        mono_ctx = detect_monorepo(config_dir)

    if mono_ctx is None:
        # Not a monorepo — plain single-pass run.
        return apply_command(
            ApplyOptions(
                config_path=config_path.resolve(),
                check_only=check_only,
                strict=strict,
            ),
        )

    # Validate --member filter.
    if member:
        matching = [m for m in mono_ctx.members if str(m.path) == member or m.name == member]
        if not matching:
            from repolish.commands.apply.display import error_unknown_member  # noqa: PLC0415

            error_unknown_member(member, [m.name for m in mono_ctx.members])
            return 1
        target_members = matching
    else:
        target_members = mono_ctx.members

    # Dry pass: collect member ProviderEntry objects + emitted inputs.
    # Always runs (even with --root-only) so root providers see member data.
    member_data = collect_member_data(mono_ctx.members, config_dir, mono_ctx)
    all_member_entries = [e for md in member_data for e in md.provider_entries]
    all_member_inputs = [i for md in member_data for i in md.emitted_inputs]

    # Root pass (skipped when --member is given).
    if not member:
        root_mono_ctx = MonorepoContext(
            mode='root',
            root_dir=config_dir,
            members=mono_ctx.members,
        )
        rc = _run_project_session(
            config_path,
            root_mono_ctx,
            check_only=check_only,
            strict=strict,
            extra_provider_entries=all_member_entries or None,
            extra_inputs=all_member_inputs or None,
        )
        if rc != 0:
            return rc

    # Member passes (skipped when --root-only).
    if not root_only:
        for m in target_members:
            member_mono_ctx = MonorepoContext(
                mode='package',
                root_dir=config_dir,
                package_dir=config_dir / m.path,
                members=mono_ctx.members,
            )
            member_config = config_dir / m.path / 'repolish.yaml'
            rc = _run_project_session(
                member_config,
                member_mono_ctx,
                check_only=check_only,
                strict=strict,
            )
            if rc != 0:
                return rc

    return 0
