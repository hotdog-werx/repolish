from pathlib import Path

from cyclopts import Parameter
from hotlog import get_logger
from pydantic import BaseModel, Field

from repolish.cli.utils import run_cli_command

logger = get_logger(__name__)


@Parameter(name='*')
class PreviewParams(BaseModel):
    """Parameters for the preview command."""

    debug_file: Path = Field(
        description='Path to the YAML debug configuration file',
    )
    show_patterns: bool = Field(
        default=False,
        description='Show extracted patterns from template',
    )
    show_steps: bool = Field(
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
