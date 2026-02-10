"""Provider management and CLI execution."""

import json
import shlex
import subprocess
from pathlib import Path

from hotlog import get_logger

from repolish.config.models import ProviderInfo
from repolish.config.providers import get_provider_info_path

logger = get_logger(__name__)


def save_provider_alias(alias: str, folder_name: str, config_dir: Path) -> None:
    """Save an alias mapping for a provider.

    Args:
        alias: The alias name used in the config
        folder_name: The provider folder name within .repolish/ (e.g., 'codeguide')
        config_dir: Directory containing the repolish.yaml file
    """
    repolish_dir = config_dir / '.repolish' / '_'
    aliases_file = repolish_dir / '.all-providers.json'

    # Load existing data
    data = {'aliases': {}}
    if aliases_file.exists():
        with aliases_file.open('r') as f:
            data = json.load(f)

    # Update with new alias (store only folder name)
    data['aliases'][alias] = folder_name

    # Save data
    repolish_dir.mkdir(parents=True, exist_ok=True)
    with aliases_file.open('w') as f:
        json.dump(data, f, indent=2)

    logger.debug('provider_alias_saved', alias=alias, folder=folder_name)


def save_provider_info(
    provider_name: str,
    provider_info: ProviderInfo,
    config_dir: Path,
) -> None:
    """Save provider info to .repolish/_/provider-info.[alias].json.

    This allows repolish to auto-build directories from providers_order.
    Also saves an alias mapping so the provider can be referenced by its config name.

    Args:
        provider_name: Alias name of the provider
        provider_info: Provider information from the CLI --info output
        config_dir: Directory containing the repolish.yaml file
    """
    target_dir = Path(provider_info.target_dir)
    repolish_dir = config_dir / '.repolish' / '_'
    repolish_dir.mkdir(parents=True, exist_ok=True)

    info_file = get_provider_info_path(provider_name, config_dir)

    logger.debug(
        'saving_provider_info',
        provider=provider_name,
        info_file=str(info_file),
        info=provider_info.model_dump(),
    )

    # Ensure target directory exists
    target_dir.mkdir(parents=True, exist_ok=True)

    # Save the info (use mode='json' to trigger field serializers for Path -> str conversion)
    with info_file.open('w') as f:
        json.dump(provider_info.model_dump(mode='json'), f, indent=2)

    # Save alias mapping - extract folder name from target_dir
    folder_name = target_dir.relative_to(config_dir / '.repolish').parts[0]
    save_provider_alias(provider_name, folder_name, config_dir)

    logger.debug(
        'provider_info_saved',
        provider=provider_name,
        folder=folder_name,
    )


def run_provider_link(provider_name: str, link_command: str) -> ProviderInfo:
    """Run a provider's link CLI and return its info.

    Args:
        provider_name: Name of the provider
        link_command: CLI command to run (e.g., 'codeguide-link' or 'codeguide-link -v')

    Returns:
        Provider information from --info flag

    Raises:
        subprocess.CalledProcessError: If the link command fails
    """
    logger.info(
        'running_provider_link',
        provider=provider_name,
        command=link_command,
        _display_level=1,
    )

    # Split command to handle arguments (e.g., "codeguide-link -v")
    cmd_parts = shlex.split(link_command)

    # First get info from the CLI
    logger.debug('getting_provider_info', command=f'{link_command} --info')
    # S603: subprocess call is intentional - we need to call provider link CLIs
    # configured by the user (e.g., 'codeguide-link'). This is the core
    # functionality of repolish-link and the commands are from the config file.
    result = subprocess.run(  # noqa: S603
        [*cmd_parts, '--info'],
        capture_output=True,
        text=True,
        check=True,
    )
    cli_info_dict = json.loads(result.stdout)
    provider_info = ProviderInfo.model_validate(cli_info_dict)

    # Now run the actual link command
    logger.debug('running_link_command', command=link_command)
    # S603: subprocess call is intentional - see comment above
    subprocess.run(  # noqa: S603
        cmd_parts,
        check=True,
    )

    logger.info(
        'provider_linked',
        provider=provider_name,
        target=provider_info.target_dir,
        _display_level=1,
    )

    return provider_info
