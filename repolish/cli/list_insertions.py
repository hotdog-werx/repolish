from pathlib import Path
from typing import Annotated

from cyclopts import Parameter
from pydantic import BaseModel, Field

from repolish.cli.utils import run_cli_command


@Parameter(name='*')
class ListInsertionsParams(BaseModel):
    """Parameters for the list-insertions command."""

    config: Annotated[Path, Parameter(name=['--config', '-c'])] = Field(
        default=Path('repolish.yaml'),
        description='Path to the repolish YAML configuration file',
    )
    provider: Annotated[str | None, Parameter(name=['--provider', '-p'])] = Field(
        default=None,
        description='Filter by provider alias',
    )
    function: Annotated[str | None, Parameter(name=['--function', '-f'])] = Field(
        default=None,
        description='Filter by insertion function name',
    )


_DEFAULT_PARAMS = ListInsertionsParams()


def list_insertions(params: ListInsertionsParams = _DEFAULT_PARAMS) -> None:
    """List insertion functions available from configured providers."""
    from repolish.commands.list_insertions import (  # noqa: PLC0415
        ListInsertionsOptions,
        command,
    )

    run_cli_command(
        lambda: command(
            ListInsertionsOptions(
                config_path=params.config,
                provider=params.provider,
                function=params.function,
            ),
        ),
    )
