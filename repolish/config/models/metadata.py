from pathlib import Path

from hotlog import get_logger
from pydantic import BaseModel, Field, ValidationError

logger = get_logger(__name__)


class AllProviders(BaseModel):
    """Model for .all-providers.json file structure.

    This file stores provider alias mappings and can be expanded in the future
    to include additional provider metadata or configuration.

    Aliases map user-friendly names to provider folder names within .repolish/.
    Example: {"aliases": {"base": "devkit", "py": "python-tools"}}
    """

    aliases: dict[str, str] = Field(
        default_factory=dict,
        description='Mapping of alias names to provider folder names (not full paths)',
    )

    @classmethod
    def from_file(cls, file_path: Path) -> 'AllProviders':
        """Load provider data from JSON file.

        Args:
            file_path: Path to .all-providers.json file

        Returns:
            AllProviders model with empty aliases dict if file doesn't exist or is invalid

        Note:
            Returns a model with empty aliases (not None) because not having this file
            is normal - it just means no provider aliases are configured yet.
        """
        if not file_path.exists():
            return cls()

        try:
            return cls.model_validate_json(file_path.read_text())
        except (ValidationError, ValueError) as e:
            logger.warning(
                'invalid_all_providers_file',
                file=str(file_path),
                error=str(e),
            )
            return cls()


class ProviderFileInfo(BaseModel):
    """On-disk record written and read by the linker for a single linked provider.

    Persisted as `.provider-info.<alias>.json` inside the project's `.repolish/`
    directory. Only the linker and the config resolution layer should need this
    model; nothing in the provider-authoring or session-execution path uses it.

    The three path fields capture the layout of a provider:

    - `resources_dir`: where the provider's resources live inside the project
      (the symlink target created by the linker CLI, e.g. `.repolish/devkit-workspace/`).
    - `provider_root`: the directory containing `repolish.py` and the
      `repolish/` template tree. May equal `resources_dir` when there is
      no subdirectory offset. Empty string means "same as resources_dir".
    - `site_package_dir`: absolute path to the provider's resources inside
      its installed Python package (e.g. `/site-packages/devkit_workspace/resources/`).
      Informational only; empty for local / directory-only providers.
    """

    resources_dir: str = Field(
        description=(
            'Directory where provider resources are linked into the project (e.g. .repolish/devkit-workspace/).'
        ),
    )
    provider_root: str = Field(
        default='',
        description=(
            'Directory containing repolish.py and the repolish/ template tree.'
            ' Empty string means the same directory as resources_dir.'
        ),
    )
    site_package_dir: str = Field(
        default='',
        description=(
            'Absolute path to the provider resources inside its installed Python package. Empty for local providers.'
        ),
    )
    project_name: str = Field(
        default='',
        description='Project name as declared in pyproject.toml [project] name (e.g. "devkit-workspace")',
    )
    package_name: str = Field(
        default='',
        description='Python package name (import name) for the provider (e.g. "devkit_workspace")',
    )

    @classmethod
    def from_file(cls, file_path: Path) -> 'ProviderFileInfo | None':
        """Load provider info from a `.provider-info.<alias>.json` file.

        Returns the parsed `ProviderFileInfo`, or `None` if the file does not
        exist or cannot be validated.
        """
        if not file_path.exists():
            logger.debug('provider_info_file_not_found', file=str(file_path))
            return None

        try:
            info = cls.model_validate_json(file_path.read_text())
            logger.debug(
                'loaded_provider_info',
                file=str(file_path),
                data=info.model_dump(mode='json'),
            )
        except (ValidationError, ValueError) as e:
            logger.warning(
                'invalid_provider_info_file',
                file=str(file_path),
                error=str(e),
            )
            return None
        else:
            return info
