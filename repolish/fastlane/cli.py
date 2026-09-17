"""The generated per-provider CLI for fast lanes.

:func:`provider_cli` builds a cyclopts app with one subcommand per lane
declared by :meth:`~repolish.providers.models.Provider.create_fast_lanes`,
plus an ``all`` subcommand for the provider's full pass. :func:`run_lane` is
the runtime behind every subcommand: it reads the project's real
``repolish.yaml`` (so ``paused_files`` and the provider's own ``overrides``
are honored) and runs the single-provider pipeline with the dry pass
skipped.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import cyclopts
from cyclopts import Parameter
from hotlog import configure_logging, get_logger, resolve_verbosity

from repolish.cli.apply import ApplyCommonParams
from repolish.cli.utils import run_cli_command
from repolish.exceptions import ConfigValidationError

if TYPE_CHECKING:
    from collections.abc import Callable

    from repolish.config.models import RepolishConfig
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


def _resolve_alias(
    config: RepolishConfig,
    provider_root: Path,
    *,
    alias: str | None,
) -> str:
    """Return the configured alias whose provider_root is *provider_root*.

    An explicit *alias* always wins. Otherwise the config entry registered
    for this package (what ``repolish link`` writes) is matched by its
    resolved ``provider_root``; a miss means the provider is not linked into
    the project yet.
    """
    if alias is not None:
        if alias not in config.providers:
            msg = f'alias {alias!r} is not defined in repolish.yaml providers'
            raise ConfigValidationError(msg)
        return alias
    wanted = provider_root.resolve()
    for name, info in config.providers.items():
        if info.provider_root.resolve() == wanted:
            return name
    msg = (
        f'no repolish.yaml provider entry points at {wanted}. Run '
        f'repolish link (or add the provider to repolish.yaml) and try again.'
    )
    raise ConfigValidationError(msg)


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

    Reads the project's ``repolish.yaml`` exactly like ``repolish apply``
    would, so ``paused_files`` and this provider's ``overrides`` are
    honored, then runs the single-provider pipeline with the dry pass
    skipped and only the selected lane's contributions staged.
    """
    # Deferred imports: repolish.fastlane is imported by the apply pipeline,
    # so the session modules must not be pulled in at import time.
    from repolish.commands.apply.display import print_summary_tree  # noqa: PLC0415
    from repolish.commands.apply.options import ApplyOptions  # noqa: PLC0415
    from repolish.commands.apply.pipeline import resolve_session  # noqa: PLC0415
    from repolish.commands.apply.session import apply_session  # noqa: PLC0415
    from repolish.config import load_config  # noqa: PLC0415

    configure_logging(verbosity=resolve_verbosity(verbose=verbose))
    config_path = config.resolve()
    if not config_path.is_file():
        msg = f'config file not found: {config_path}. Run this command from the project root.'
        raise ConfigValidationError(msg)

    resolved = load_config(config_path)
    lane_alias = _resolve_alias(resolved, provider_root, alias=alias)
    logger.info(
        'lane_started',
        lane=lane or 'all',
        alias=lane_alias,
        config=str(config_path),
    )

    options = ApplyOptions(
        config_path=config_path,
        check_only=check,
        skip_post_process=skip_post_process,
        fail_on_warnings=fail_on_warnings,
        provider_filter=[lane_alias],
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
    print_summary_tree([session])
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
    lanes = inst.create_fast_lanes()

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
