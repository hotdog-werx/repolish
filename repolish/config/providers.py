from pathlib import Path

from repolish.config.models import AllProviders, ProviderInfo


def get_provider_info_path(provider_alias: str, config_dir: Path) -> Path:
    """Get the path to a provider's info file.

    Args:
        provider_alias: Name of the provider (alias name)
        config_dir: Directory containing the repolish.yaml file

    Returns:
        Path to the provider info file
    """
    return config_dir / '.repolish' / '_' / f'provider-info.{provider_alias}.json'


def resolve_provider_alias(
    provider_alias: str,
    config_dir: Path,
) -> str | None:
    """Resolve a provider alias to its actual directory path.

    Args:
        provider_alias: Provider name (may be an alias)
        config_dir: Directory containing the repolish.yaml file

    Returns:
        Relative path to provider directory, or None if not an alias
    """
    aliases_file = config_dir / '.repolish' / '_' / '.all-providers.json'
    all_providers = AllProviders.from_file(aliases_file)
    folder_name = all_providers.aliases.get(provider_alias)
    return f'.repolish/{folder_name}' if folder_name else None


def load_provider_info(
    provider_alias: str,
    config_dir: Path,
) -> ProviderInfo | None:
    """Load provider info from .repolish/_/provider-info.[alias].json.

    Provider info files are now centralized in .repolish/_/ directory
    and named with the alias (e.g., provider-info.base.json).

    Args:
        provider_alias: Name of the provider (alias name)
        config_dir: Directory containing the repolish.yaml file

    Returns:
        ProviderInfo model or None if not found
    """
    info_file = get_provider_info_path(provider_alias, config_dir)
    return ProviderInfo.from_file(info_file)
