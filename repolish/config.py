from pathlib import Path
from typing import Any

import yaml
from hotlog import get_logger
from pydantic import BaseModel, Field

logger = get_logger(__name__)


class RepolishConfig(BaseModel):
    """Configuration for the Repolish tool."""

    directories: list[str] = Field(
        default=...,
        description='List of paths to template directories',
        min_length=1,
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description='Context variables for template rendering',
    )
    post_process: list[str] = Field(
        default_factory=list,
        description='List of shell commands to run after generating files (formatters)',
    )

    def _handle_directory_errors(
        self,
        missing_dirs: list[str],
        invalid_dirs: list[str],
        invalid_template: list[str],
    ) -> None:
        """Handle errors related to directory validation."""
        error_messages = []
        if missing_dirs:
            error_messages.append(f'Missing directories: {missing_dirs}')
        if invalid_dirs:
            error_messages.append(
                f'Invalid directories (not a directory): {invalid_dirs}',
            )
        if invalid_template:
            error_messages.append(
                f'Directories missing repolish.py: {invalid_template}',
            )
        if error_messages:
            raise ValueError(' ; '.join(error_messages))

    def validate_directories(self) -> None:
        """Validate that all directories exist."""
        missing_dirs: list[str] = []
        invalid_dirs: list[str] = []
        invalid_template: list[str] = []

        for directory in self.directories:
            path = Path(directory)
            if not path.exists():
                missing_dirs.append(directory)
            elif not path.is_dir():
                invalid_dirs.append(directory)
            elif not (path / 'repolish.py').exists():
                invalid_template.append(directory)

        if missing_dirs or invalid_dirs or invalid_template:
            self._handle_directory_errors(
                missing_dirs,
                invalid_dirs,
                invalid_template,
            )


def load_config(yaml_file: Path) -> RepolishConfig:
    """Find the repolish configuration file in the specified directory.

    Args:
        yaml_file: Path to the YAML configuration file.

    Returns:
        An instance of RepolishConfig with validated data.
    """
    with yaml_file.open(encoding='utf-8') as f:
        data = yaml.safe_load(f)
    config = RepolishConfig.model_validate(data)
    config.validate_directories()
    return config
