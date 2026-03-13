from pathlib import Path

from hotlog import get_logger
from pydantic import BaseModel, Field, ValidationError

from repolish.config.models.provider import ProviderSymlink

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


class ProviderInfo(BaseModel):
    """Model for .provider-info.json file structure.

    Contains information about a linked provider.
    """

    target_dir: str = Field(
        description='Directory where provider resources are linked',
    )
    source_dir: str = Field(
        description='Directory where provider resources originate (e.g., in site-packages)',
    )
    # Deprecated: providers now specify the template root directly via
    # `target_dir`.  Historically we allowed a separate
    # ``templates_dir`` within the provider folder, but configuration and
    # resolution no longer rely on this field.  The attribute is omitted from
    # the model to keep the serialized JSON compact; older files may still
    # contain the key and it will be ignored by the loader.
    library_name: str | None = Field(
        default=None,
        description='Name of the provider library (optional)',
    )
    project_name: str = Field(
        default='',
        description='Project name as declared in pyproject.toml [project] name (e.g. "devkit-workspace")',
    )
    package_name: str = Field(
        default='',
        description='Python package name (import name) for the provider (e.g. "devkit_workspace")',
    )
    symlinks: list[ProviderSymlink] = Field(
        default_factory=list,
        description='Default symlinks provided by the provider',
    )

    @classmethod
    def from_file(cls, file_path: Path) -> 'ProviderInfo | None':
        """Load provider info from JSON file.

        Args:
            file_path: Path to .provider-info.json file

        Returns:
            ProviderInfo instance or None if file doesn't exist or is invalid
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
