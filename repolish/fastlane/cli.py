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
import sys
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from time import perf_counter
from typing import TYPE_CHECKING, Annotated, Any

import cyclopts
from cyclopts import Parameter
from hotlog import configure_logging, get_logger, resolve_verbosity
from pydantic import BaseModel, create_model

from repolish.cli.apply import ApplyCommonParams
from repolish.cli.utils import run_cli_command
from repolish.providers.models import (
    FastLaneSpec,
    ProviderCommandContext,
    ProviderCommandExecutor,
    ProviderInfo,
    RepolishContext,
    get_global_context,
)
from repolish.providers.models.mapping_normalization import (
    normalize_lane_spec_mappings,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from repolish.providers.models import GlobalContext, Provider

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
    cli_name: str,
    lane_spec: FastLaneSpec | None = None,
    alias: str | None = None,
    config: Path = Path('repolish.yaml'),
    check: bool = False,
    skip_post_process: bool = False,
    fail_on_warnings: bool = False,
    verbose: int = 0,
    global_context: GlobalContext | None = None,
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

    When *global_context* is ``None`` the session pipeline computes one via
    :func:`get_global_context`; a caller that already built one (provider
    commands, for the executor's ``ProviderCommandContext``) passes it here
    so the executor and the rendered templates see identical values.
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
        cli_name=cli_name,
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
        lane_spec=lane_spec,
        global_context=global_context,
        skip_dry_pass=True,
        command_only=lane_spec is not None,
        fast_lanes_only=lane is not None and lane_spec is None,
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


class _CommandCommonParams(BaseModel):
    """Option-only flags shared by generated provider command subcommands."""

    config: Annotated[Path, Parameter(name=['--config', '-c'])] = Path(
        'repolish.yaml',
    )
    check: Annotated[bool, Parameter(name=['--check'])] = False
    fail_on_warnings: Annotated[
        bool,
        Parameter(name=['--fail-on-warnings']),
    ] = False
    skip_post_process: Annotated[
        bool,
        Parameter(name=['--skip-post-process']),
    ] = False
    verbose: Annotated[
        int,
        Parameter(
            name=['-v', '--verbose'],
            count=True,
            help='Increase verbosity (-v, -vv).',
        ),
    ] = 0


@dataclass(frozen=True)
class _ProviderCommandSpec:
    provider_root: Path
    cli_name: str
    provider_alias: str
    command_name: str
    args_model: type[BaseModel]
    executor: ProviderCommandExecutor


def _normalize_command_spec(
    spec: FastLaneSpec,
    *,
    provider_id: str,
) -> FastLaneSpec:
    """Return a lane spec normalized for pipeline lane execution.

    Provider command executors return lane-like contributions directly, outside
    the provider collection path. This helper mirrors lane normalization so
    source-provider bookkeeping and plain-string mappings behave consistently.
    """
    return normalize_lane_spec_mappings(
        spec,
        provider_id=provider_id,
        keep_existing_source_provider=True,
    )


def _lane_command(
    provider_root: Path,
    lane: str | None,
    *,
    cli_name: str,
    alias: str | None,
) -> Callable:
    """Build one lane subcommand function for :func:`provider_cli`."""
    default_params = LaneParams()

    def _run(params: LaneParams = default_params) -> None:
        run_cli_command(
            lambda: run_lane(
                provider_root,
                lane,
                cli_name=cli_name,
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


def _command_params_model(
    command_name: str,
    args_model: type[BaseModel],
) -> type[BaseModel]:
    """Build a merged params model containing option flags and command args."""
    safe_name = command_name.replace('-', '_').replace(':', '_').title().replace('_', '')
    model_name = f'{safe_name}Params'
    fields: dict[str, Any] = {}
    for field_name, field_info in args_model.model_fields.items():
        default = ... if field_info.is_required() else field_info.default
        opt_name = field_name.replace('_', '-')
        annotated = Annotated[
            field_info.annotation,
            Parameter(name=[opt_name, f'--{opt_name}']),
        ]
        fields[field_name] = (annotated, default)
    fields['config'] = (
        Annotated[Path, Parameter(name=['--config', '-c'])],
        Path('repolish.yaml'),
    )
    fields['check'] = (
        Annotated[bool, Parameter(name=['--check'])],
        False,
    )
    fields['fail_on_warnings'] = (
        Annotated[bool, Parameter(name=['--fail-on-warnings'])],
        False,
    )
    fields['skip_post_process'] = (
        Annotated[bool, Parameter(name=['--skip-post-process'])],
        False,
    )
    fields['verbose'] = (
        Annotated[
            int,
            Parameter(
                name=['-v', '--verbose'],
                count=True,
                help='Increase verbosity (-v, -vv).',
            ),
        ],
        0,
    )
    return create_model(
        model_name,
        **fields,
    )


def _provider_command(spec: _ProviderCommandSpec) -> Callable:
    """Build one provider command subcommand function for :func:`provider_cli`."""
    params_model = _command_params_model(spec.command_name, spec.args_model)

    def _run(params: Any) -> None:  # noqa: ANN401 - params is dynamically typed
        def _invoke() -> int:
            from repolish.fastlane.config import prepare_lane_config  # noqa: PLC0415

            prepared = prepare_lane_config(
                spec.provider_root,
                f'command:{spec.command_name}',
                cli_name=spec.cli_name,
                alias=spec.provider_alias or None,
                config_path=params.config.resolve(),
            )
            resolved_alias = next(
                iter(prepared.config.providers),
                spec.provider_alias,
            )
            args_payload = {
                name: getattr(params, name) for name in spec.args_model.model_fields if hasattr(params, name)
            }
            command_args = spec.args_model.model_validate(args_payload)
            # Populate the global namespace the same way the session
            # pipeline does for templates and lane hooks: repo info read
            # from the real project, so an executor reading
            # ctx.repolish.repo.name sees the same values the rendered
            # templates do (the same object is passed to run_lane below).
            global_ctx = get_global_context()
            command_ctx = ProviderCommandContext(
                repolish=RepolishContext(
                    repo=global_ctx.repo,
                    year=global_ctx.year,
                    workspace=global_ctx.workspace,
                    provider=ProviderInfo(alias=resolved_alias),
                ),
                provider_root=spec.provider_root,
                config_path=params.config.resolve(),
                check=params.check,
                skip_post_process=params.skip_post_process,
                fail_on_warnings=params.fail_on_warnings,
                verbose=params.verbose,
            )
            lane_key = f'command:{spec.command_name}'
            lane_spec = _normalize_command_spec(
                spec.executor(command_args, command_ctx),
                provider_id=str(spec.provider_root.resolve()),
            )
            return run_lane(
                spec.provider_root,
                lane_key,
                cli_name=spec.cli_name,
                lane_spec=lane_spec,
                alias=resolved_alias,
                config=params.config,
                check=params.check,
                skip_post_process=params.skip_post_process,
                fail_on_warnings=params.fail_on_warnings,
                verbose=params.verbose,
                global_context=global_ctx,
            )

        run_cli_command(_invoke)

    _run.__name__ = spec.command_name.replace('-', '_').replace(':', '_')
    _run.__annotations__['params'] = params_model
    _run.__doc__ = f'Run provider command {spec.command_name!r}.'
    return _run


def provider_cli(
    provider_class: type[Provider[Any, Any]],
    *,
    cli_name: str | None = None,
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
    commands = provider_class.create_provider_commands()
    collisions = sorted(set(lanes).intersection(commands))
    if collisions:
        msg = f'provider command names collide with fast lane names: {collisions}'
        raise ValueError(msg)

    resolved_cli_name = cli_name or Path(sys.argv[0]).name or 'provider-cli'
    provider_name = alias or provider_root.parent.parent.name
    help_text = dedent(f"""
        Generated CLI for the "{provider_name}" provider.

        Configure lane post_process entries in repolish.yaml with CLI-scoped keys:

        ```yaml
        fast_lanes:
          config:
            {resolved_cli_name}:{{lane-name}}:
              post_process:
                - <command>
            {resolved_cli_name}:command:{{command-name}}:
              post_process:
                - <command>
        ```
        """).strip()
    app = cyclopts.App(
        help=help_text,
        help_format='markdown',
    )
    for lane_name in lanes:
        app.command(
            _lane_command(
                provider_root,
                lane_name,
                cli_name=resolved_cli_name,
                alias=alias,
            ),
            name=str(lane_name),
        )
    app.command(
        _lane_command(
            provider_root,
            None,
            cli_name=resolved_cli_name,
            alias=alias,
        ),
        name='all',
    )
    for command_name, contract in commands.items():
        app.command(
            _provider_command(
                _ProviderCommandSpec(
                    provider_root=provider_root,
                    cli_name=resolved_cli_name,
                    provider_alias=inst.alias,
                    command_name=str(command_name),
                    args_model=contract.args_model,
                    executor=contract.executor,
                ),
            ),
            name=str(command_name),
            help=contract.summary or None,
        )
    return app
