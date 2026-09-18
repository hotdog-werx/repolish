"""The generated per-provider CLI for fast lanes.

:func:`provider_cli` builds a cyclopts app with one subcommand per lane
declared by :meth:`~repolish.providers.models.Provider.create_fast_lanes`,
plus an ``all`` subcommand for the provider's full pass. :func:`run_lane` is
the runtime behind every subcommand: it prepares the run's configuration
from the project's ``repolish.yaml`` when one exists (honoring
``paused_files``, the ``fast_lanes`` section, and the provider's own entry
fields) and otherwise runs with an in-memory single-provider configuration,
so the CLI works in any project, registered or not. No provider
registration, readiness check, or link command ever runs.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Annotated, Any

import cyclopts
from cyclopts import Parameter
from hotlog import configure_logging, get_logger, resolve_verbosity

from repolish.cli.apply import ApplyCommonParams
from repolish.cli.utils import run_cli_command
from repolish.providers.models import ProviderInfo, RepolishContext

if TYPE_CHECKING:
    from collections.abc import Callable

    from repolish.providers.models import Provider

logger = get_logger(__name__)


def _locate_provider_root(provider_cls: type[Provider[Any, Any]]) -> Path:
    """Discover the ``resources/templates`` directory for *provider_cls*.

    Walks up from the provider class's module to the package root looking
    for a ``resources/templates`` directory, mirroring what the resource
    linker registers at install time. Local to this module so the CLI
    factory does not depend on the testing package.
    """
    mod = importlib.import_module(provider_cls.__module__)
    mod_file = getattr(mod, '__file__', None)
    if mod_file is None:  # pragma: no cover - namespace packages
        msg = f'cannot locate source for {provider_cls.__module__}'
        raise RuntimeError(msg)
    pkg_dir = Path(mod_file).resolve().parent
    for ancestor in [pkg_dir, *pkg_dir.parents]:
        candidate = ancestor / 'resources' / 'templates'
        if candidate.is_dir():
            return candidate
        if (ancestor / 'pyproject.toml').exists():
            break
    msg = f'cannot find resources/templates for {provider_cls.__name__}'
    raise RuntimeError(msg)


def run_lane(  # noqa: PLR0913 - mirrors the apply CLI flag set on purpose
    provider_root: Path,
    lane: str | None,
    *,
    alias: str | None = None,
    config: Path = Path('repolish.yaml'),
    check: bool = False,
    skip_post_process: bool = False,
    fail_on_warnings: bool = False,
    verbose: int = 0,
) -> int:
    """Run one lane (or the provider's full pass) against the real project.

    The configuration is prepared by
    :func:`~repolish.fastlane.config.prepare_lane_config`: a single raw YAML
    read when ``repolish.yaml`` exists (honoring ``paused_files``, the
    ``fast_lanes`` section, and this provider's entry fields), an in-memory
    configuration otherwise. The provider never has to be registered in the
    project, and no readiness check or link command runs. A named lane runs
    only its own ``fast_lanes.config`` post-process commands; ``all`` runs
    the project's.
    """
    # Deferred imports: repolish.fastlane is imported by the apply pipeline,
    # so the session modules must not be pulled in at import time.
    from repolish.commands.apply.display import (  # noqa: PLC0415
        print_run_footer,
        print_run_summary,
    )
    from repolish.commands.apply.options import ApplyOptions  # noqa: PLC0415
    from repolish.commands.apply.pipeline import resolve_session  # noqa: PLC0415
    from repolish.commands.apply.session import apply_session  # noqa: PLC0415
    from repolish.fastlane.config import prepare_lane_config  # noqa: PLC0415
    from repolish.reporting import print_run_header  # noqa: PLC0415

    configure_logging(verbosity=resolve_verbosity(verbose=verbose))
    started = perf_counter()
    config_path = config.resolve()
    prepared = prepare_lane_config(
        provider_root,
        lane,
        alias=alias,
        config_path=config_path,
    )
    lane_alias = next(iter(prepared.config.providers))
    logger.debug(
        'lane_started',
        lane=lane or 'all',
        alias=lane_alias,
        config=str(config_path),
    )
    print_run_header(
        [
            f'lane {lane or "all"}',
            f'provider {lane_alias}',
            config_path.name,
        ],
    )

    options = ApplyOptions(
        config_path=config_path,
        check_only=check,
        skip_post_process=skip_post_process,
        fail_on_warnings=fail_on_warnings,
        provider_filter=[lane_alias],
        lane_config=prepared,
        lane=lane,
        skip_dry_pass=True,
    )
    session = resolve_session(options)
    rc = apply_session(
        session,
        check_only=check,
        skip_post_process=skip_post_process,
        fail_on_warnings=fail_on_warnings,
    )
    print_run_summary([session])
    print_run_footer(
        [session],
        (perf_counter() - started) * 1000,
        config_path.parent,
    )
    return rc


@Parameter(name='*')
class LaneParams(ApplyCommonParams):
    """Parameters for one lane subcommand.

    Derives from the apply CLI's shared parameter model so the flag sets
    cannot drift: every flag on :class:`~repolish.cli.apply.ApplyCommonParams`
    is available here too. The one addition is verbosity, which the root
    ``repolish`` app handles via its meta callback but a standalone lane app
    must take per command.
    """

    verbose: Annotated[
        int,
        Parameter(
            name=['-v', '--verbose'],
            count=True,
            help='Increase verbosity (-v, -vv).',
        ),
    ] = 0


def _lane_command(
    provider_root: Path,
    lane: str | None,
    *,
    alias: str | None,
) -> Callable:
    """Build one lane subcommand function for :func:`provider_cli`."""
    default_params = LaneParams()

    def _run(params: LaneParams = default_params) -> None:
        run_cli_command(
            lambda: run_lane(
                provider_root,
                lane,
                alias=alias,
                config=params.config,
                check=params.check,
                skip_post_process=params.skip_post_process,
                fail_on_warnings=params.fail_on_warnings,
                verbose=params.verbose,
            ),
        )

    label = lane or 'all'
    _run.__name__ = label.replace('-', '_').replace(':', '_')
    _run.__doc__ = (
        f'Run the {label!r} fast lane.'
        if lane
        else 'Run every lane merged with the regular provider pass (still fast: single provider, no dry pass).'
    )
    return _run


def provider_cli(
    provider_class: type[Provider[Any, Any]],
    *,
    alias: str | None = None,
) -> cyclopts.App:
    """Build the per-provider fast-lane CLI for *provider_class*.

    Subcommands are generated from the provider's
    :meth:`~repolish.providers.models.Provider.create_fast_lanes` hook, so a
    new lane needs no ``pyproject.toml`` edits. Each subcommand accepts the
    apply flags (``--config``, ``--check``, ``--skip-post-process``,
    ``--fail-on-warnings``, ``-v``); an extra ``all`` subcommand runs the
    provider's full pass with the same fast single-provider runtime.

    Assign the result to ``main`` and register it as a project script::

        from repolish.fastlane import provider_cli
        from mylib.repolish import MyProvider

        main = provider_cli(MyProvider)

    In pyproject.toml::

        [project.scripts]
        mylib-cli = 'mylib.cli:main'
    """
    provider_root = _locate_provider_root(provider_class)
    inst = provider_class()
    inst.templates_root = provider_root
    inst.alias = alias or ''
    # Enumeration only: just lane names matter here, and no session context
    # exists yet, so the hook gets a minimal namespace (placeholder repo info,
    # the known alias). Runtime subcommands re-collect with the real one.
    lanes = inst.create_fast_lanes(
        RepolishContext(provider=ProviderInfo(alias=inst.alias)),
    )

    provider_name = type(inst).__name__
    app = cyclopts.App(
        help=f'Quick scoped apply runs for {provider_name} fast lanes.',
    )
    for lane_name in lanes:
        app.command(
            _lane_command(provider_root, lane_name, alias=alias),
            name=str(lane_name),
        )
    app.command(
        _lane_command(provider_root, None, alias=alias),
        name='all',
    )
    return app
