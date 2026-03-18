from pathlib import Path
from typing import Annotated

from cyclopts import Parameter
from hotlog import get_logger
from pydantic import BaseModel, Field

from repolish.cli.utils import run_cli_command
from repolish.commands.link import command

logger = get_logger(__name__)


@Parameter(name='*')
class LinkParams(BaseModel):
    """Parameters for the link command."""

    config: Annotated[Path, Parameter(name=['--config', '-c'])] = Field(
        default=Path('repolish.yaml'),
        description='Path to the repolish YAML configuration file',
    )


_DEFAULT_LINK_PARAMS = LinkParams()


def link(params: LinkParams = _DEFAULT_LINK_PARAMS) -> None:
    """Link provider resources to the project."""
    run_cli_command(lambda: command(params.config))
