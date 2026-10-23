from pathlib import Path
from typing import Annotated

from cyclopts import Parameter
from hotlog import get_logger
from pydantic import BaseModel, Field

from repolish.cli.utils import run_cli_command

logger = get_logger(__name__)


@Parameter(name='*')
class LinkParams(BaseModel):
    """Parameters for the link command.

    ALIAS and MODULE must be the first fields: cyclopts assigns
    positional arguments to parameters in field order, so the two
    positionals have to precede the boolean flags to bind correctly.
    """

    alias: Annotated[str | None, Parameter(name='ALIAS')] = Field(
        default=None,
        description=(
            'Link only the provider aliased ALIAS in repolish.yaml. '
            'With MODULE, instead links MODULE under ALIAS as a one-off '
            'that does not require a config entry.'
        ),
    )
    module: Annotated[str | None, Parameter(name='MODULE')] = Field(
        default=None,
        description=('Dotted module name for a one-off link under ALIAS (e.g. devkit.workspace). Requires ALIAS.'),
    )
    config: Annotated[Path, Parameter(name=['--config', '-c'])] = Field(
        default=Path('repolish.yaml'),
        description='Path to the repolish YAML configuration file',
    )
    force: Annotated[bool, Parameter(name='--force')] = Field(
        default=False,
        description='Force re-linking all providers even if already linked',
    )
    no_config: Annotated[bool, Parameter(name='--no-config')] = Field(
        default=False,
        description=(
            'Do not read the repolish YAML configuration. Requires an '
            'ALIAS and MODULE pair; with a config file present, its '
            'entry for ALIAS is explicitly ignored.'
        ),
    )
    register_only: Annotated[bool, Parameter(name='--register-only')] = Field(
        default=False,
        description=(
            'Register providers only: create the .repolish/ resource link '
            'and provider info, skip project-root symlinks and copies.'
        ),
    )


_DEFAULT_LINK_PARAMS = LinkParams()


def link(params: LinkParams = _DEFAULT_LINK_PARAMS) -> None:
    """Link provider resources to the project.

    With no arguments every provider in the config file is linked. With
    ALIAS only that provider is linked. With ALIAS and MODULE the given
    module is linked under ALIAS as a one-off, without requiring a config
    entry.
    """
    # Deferred so that importing this CLI module does not eagerly load the link
    # command tree when a different subcommand is invoked.
    from repolish.commands.link import command  # noqa: PLC0415

    run_cli_command(
        lambda: command(
            params.config,
            force=params.force,
            alias=params.alias,
            module=params.module,
            no_config=params.no_config,
            register_only=params.register_only,
        ),
    )
