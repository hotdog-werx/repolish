"""Provider management and CLI execution."""

import json
import shlex
import subprocess
from pathlib import Path

from hotlog import get_logger

from repolish.config.models.metadata import ProviderFileInfo
from repolish.config.providers import get_provider_info_path
from repolish.utils import open_utf8

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
        with open_utf8(aliases_file, 'r') as f:
            data = json.load(f)

    # Update with new alias (store only folder name)
    data['aliases'][alias] = folder_name

    # Save data
    repolish_dir.mkdir(parents=True, exist_ok=True)
    with open_utf8(aliases_file, 'w') as f:
        json.dump(data, f, indent=2)

    logger.debug('provider_alias_saved', alias=alias, folder=folder_name)


def write_provider_info_file(
    provider_name: str,
    provider_info: ProviderFileInfo,
    config_dir: Path,
) -> None:
    """Write the provider-info JSON file to ``.repolish/_/provider-info.<alias>.json``.

    This is the single place that controls how provider info is persisted.  It
    does **not** write an alias mapping — call :func:`save_provider_info` when
    the alias mapping is also needed (i.e. resources live under ``.repolish/``).

    Args:
        provider_name: Alias name of the provider.
        provider_info: Provider information to persist.
        config_dir: Directory containing the ``repolish.yaml`` file.
    """
    info_file = get_provider_info_path(provider_name, config_dir)
    info_file.parent.mkdir(parents=True, exist_ok=True)

    logger.debug(
        'saving_provider_info',
        provider=provider_name,
        info_file=str(info_file),
        info=provider_info.model_dump(mode='json'),
    )

    with open_utf8(info_file, 'w') as f:
        json.dump(provider_info.model_dump(mode='json'), f, indent=2)


def save_provider_info(
    provider_name: str,
    provider_info: ProviderFileInfo,
    config_dir: Path,
) -> None:
    """Save provider info and its alias mapping.

    Writes the provider-info JSON file (via :func:`write_provider_info_file`)
    and records the alias → folder mapping in ``.all-providers.json``.  The
    ``resources_dir`` recorded in *provider_info* **must** live under
    ``<config_dir>/.repolish/``; use :func:`write_provider_info_file` directly
    when that assumption does not hold (e.g. local ``provider_root`` paths).

    Args:
        provider_name: Alias name of the provider.
        provider_info: Provider information from the CLI ``--info`` output.
        config_dir: Directory containing the ``repolish.yaml`` file.
    """
    resources_dir = Path(provider_info.resources_dir)

    # Ensure resources directory exists
    resources_dir.mkdir(parents=True, exist_ok=True)

    write_provider_info_file(provider_name, provider_info, config_dir)

    # Save alias mapping - extract folder name from resources_dir
    folder_name = resources_dir.relative_to(config_dir / '.repolish').parts[0]
    save_provider_alias(provider_name, folder_name, config_dir)

    logger.debug(
        'provider_info_saved',
        provider=provider_name,
        folder=folder_name,
    )


def run_provider_link(
    provider_name: str,
    link_command: str,
) -> ProviderFileInfo:
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
    provider_info = ProviderFileInfo.model_validate(cli_info_dict)

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
        target=str(provider_info.resources_dir),
        _display_level=1,
    )

    return provider_info
