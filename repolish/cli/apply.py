from pathlib import Path
from typing import Annotated

from cyclopts import Parameter
from pydantic import BaseModel, Field

from repolish.cli.utils import run_cli_command
from repolish.commands.apply import command


@Parameter(name='*')
class ApplyParams(BaseModel):
    """Parameters for the apply command."""

    config: Annotated[Path, Parameter(name=['--config', '-c'])] = Field(
        Path('repolish.yaml'),
        description='Path to the repolish YAML configuration file',
    )
    check: bool = Field(
        default=False,
        description='Load config and create context (dry-run check)',
    )


_DEFAULT_APPLY_PARAMS = ApplyParams()


def apply(params: ApplyParams = _DEFAULT_APPLY_PARAMS) -> None:
    """Apply templates to project."""
    run_cli_command(lambda: command(params.config, check_only=params.check))
