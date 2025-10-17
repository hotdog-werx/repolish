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
    anchors: dict[str, str] = Field(
        default_factory=dict,
        description='Anchor content for block replacements',
    )
    post_process: list[str] = Field(
        default_factory=list,
        description='List of shell commands to run after generating files (formatters)',
    )
    delete_files: list[str] = Field(
        default_factory=list,
        description=(
            'List of POSIX-style paths to delete after generation. Use a leading'
            " '!' to negate (keep) a previously-added path."
        ),
    )
    # Path to the YAML configuration file. Set when loading from disk; excluded
    # from model serialization so it doesn't appear in dumped config data.
    config_file: Path | None = Field(
        default=None,
        description='Path to the YAML configuration file (set by loader)',
        exclude=True,
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
                f'Directories missing repolish.py or repolish/ folder: {invalid_template}',
            )
        if error_messages:
            raise ValueError(' ; '.join(error_messages))

    def validate_directories(self) -> None:
        """Validate that all directories exist."""
        missing_dirs: list[str] = []
        invalid_dirs: list[str] = []
        invalid_template: list[str] = []

        for directory in self.get_directories():
            # Keep the user-facing identifier as the original string for
            # clearer error messages; find the matching input string by index.
            idx = self.get_directories().index(directory)
            original = self.directories[idx]
            path = directory
            if not path.exists():
                missing_dirs.append(original)
            elif not path.is_dir():
                invalid_dirs.append(original)
            elif not (path / 'repolish.py').exists() or not (path / 'repolish').exists():
                invalid_template.append(original)

        if missing_dirs or invalid_dirs or invalid_template:
            self._handle_directory_errors(
                missing_dirs,
                invalid_dirs,
                invalid_template,
            )

    def get_directories(self) -> list[Path]:
        """Return the configured directories as resolved Path objects.

        The YAML configuration file is expected to use POSIX-style paths (with
        forward slashes). This method interprets each configured string as a
        POSIX path and resolves it relative to the directory containing the
        configuration file (if `config_file` is set). If `config_file` is not
        set, paths are returned as-is (interpreted by the current platform).
        """
        resolved: list[Path] = []
        base_dir = Path(self.config_file).resolve().parent if self.config_file else None

        for entry in self.directories:
            # Accept POSIX-style entries (forward slashes) but let the
            # platform-native Path handle parsing so absolute Windows-style
            # entries like 'C:/path' are recognized correctly. If the entry
            # is relative, resolve it against the directory containing the
            # config file (when available).
            p = Path(entry)
            if base_dir and not p.is_absolute():
                p = base_dir / p
            resolved.append(p.resolve())

        return resolved


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
    # store the location of the config file on the model so relative paths can
    # be resolved later
    config.config_file = yaml_file
    config.validate_directories()
    return config
