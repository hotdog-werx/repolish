from pathlib import Path
from typing import Annotated

from cyclopts import Parameter
from hotlog import get_logger
from pydantic import BaseModel, Field

from repolish.cli.utils import run_cli_command

logger = get_logger(__name__)


@Parameter(name='*')
class PreviewParams(BaseModel):
    """Parameters for the preview command.

    Every field carries an explicit cyclopts ``Parameter`` name: the docs
    insertion renderer (``internal/local_provider/docs_insertions.py``)
    reads them to build the preview argument table, and it refuses fields
    whose names would have to be derived.
    """

    debug_file: Annotated[Path, Parameter(name='DEBUG_FILE')] = Field(
        description='Path to the YAML debug configuration file',
    )
    show_patterns: Annotated[
        bool,
        Parameter(name=['--show-patterns']),
    ] = Field(
        default=False,
        description='Show extracted patterns from template',
    )
    show_steps: Annotated[
        bool,
        Parameter(name=['--show-steps']),
    ] = Field(
        default=False,
        description='Show intermediate processing steps',
    )


def preview(params: PreviewParams) -> None:
    """Preview/test templates."""
    # Deferred so that importing this CLI module does not eagerly load the preview
    # command tree when a different subcommand is invoked.
    from repolish.commands.preview import command  # noqa: PLC0415

    run_cli_command(
        lambda: command(
            params.debug_file,
            show_patterns=params.show_patterns,
            show_steps=params.show_steps,
        ),
    )
