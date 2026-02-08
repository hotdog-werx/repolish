"""CLI for linking provider resources to the project."""

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

from hotlog import (
    add_verbosity_argument,
    configure_logging,
    get_logger,
    resolve_verbosity,
)

from .config import ProviderConfig, RepolishConfig, load_config
from .linker import create_additional_link

logger = get_logger(__name__)


def _save_provider_info(provider_name: str, cli_info: dict[str, str]) -> None:
    """Save provider info to .repolish/_/provider-info.[alias].json.

    This allows repolish to auto-build directories from providers_order.
    Also saves an alias mapping so the provider can be referenced by its config name.

    Args:
        provider_name: Alias name of the provider
        cli_info: Information from the provider's CLI --info (must include target_dir)
    """
    target_dir = Path(cli_info.get('target_dir', f'.repolish/{provider_name}'))
    repolish_dir = Path('.repolish') / '_'
    repolish_dir.mkdir(parents=True, exist_ok=True)

    info_file = repolish_dir / f'provider-info.{provider_name}.json'

    # Build the info dict (omit keys with None values)
    info = {
        'target_dir': str(target_dir),
    }
    if cli_info.get('templates_dir'):
        info['templates_dir'] = cli_info['templates_dir']
    if cli_info.get('library_name'):
        info['library_name'] = cli_info['library_name']

    logger.debug(
        'saving_provider_info',
        provider=provider_name,
        info_file=str(info_file),
        info=info,
    )

    # Ensure target directory exists
    target_dir.mkdir(parents=True, exist_ok=True)

    # Save the info
    with info_file.open('w') as f:
        json.dump(info, f, indent=2)

    # Save alias mapping - extract folder name from target_dir
    folder_name = target_dir.relative_to(Path('.repolish')).parts[0]
    _save_provider_alias(provider_name, folder_name)

    logger.debug(
        'provider_info_saved',
        provider=provider_name,
        folder=folder_name,
    )


def _save_provider_alias(alias: str, folder_name: str) -> None:
    """Save an alias mapping for a provider.

    Args:
        alias: The alias name used in the config
        folder_name: The provider folder name within .repolish/ (e.g., 'codeguide')
    """
    repolish_dir = Path('.repolish') / '_'
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


def run_provider_link(provider_name: str, link_command: str) -> dict[str, str]:
    """Run a provider's link CLI and return its info.

    Args:
        provider_name: Name of the provider
        link_command: CLI command to run (e.g., 'codeguide-link' or 'codeguide-link -v')

    Returns:
        Dict with provider information from --info flag

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
    cli_info = json.loads(result.stdout)

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
        target=cli_info.get('target_dir', 'unknown'),
        _display_level=1,
    )

    # Save provider info for later use by repolish
    _save_provider_info(provider_name, cli_info)

    return cli_info


def create_provider_symlinks(
    provider_name: str,
    cli_info: dict[str, str],
    symlinks: list[dict[str, str]],
) -> None:
    """Create additional symlinks for a provider.

    Args:
        provider_name: Name of the provider
        cli_info: Information from the provider's CLI --info
        symlinks: List of symlink configurations with 'source' and 'target'
    """
    if not symlinks:
        return

    logger.info(
        'creating_additional_symlinks',
        provider=provider_name,
        count=len(symlinks),
        _display_level=1,
    )

    for symlink_config in symlinks:
        source = symlink_config['source']
        target = symlink_config['target']

        logger.debug(
            'creating_symlink',
            source=source,
            target=target,
        )

        create_additional_link(
            cli_info=cli_info,
            source=source,
            target=target,
            force=True,
        )

    logger.info(
        'symlinks_created',
        provider=provider_name,
        count=len(symlinks),
        _display_level=1,
    )


def _process_single_provider(
    provider_name: str,
    provider_config: 'ProviderConfig',
) -> int:
    """Process a single provider: link resources and create symlinks.

    Args:
        provider_name: Name of the provider
        provider_config: Provider configuration

    Returns:
        0 on success, 1 on failure
    """
    # Skip providers that use direct directory (no CLI to run)
    if not provider_config.cli:
        logger.info(
            'skipping_provider_with_directory',
            provider=provider_name,
            _display_level=1,
        )
        return 0

    # Run the provider's link CLI
    try:
        cli_info = run_provider_link(
            provider_name,
            provider_config.cli,
        )
    except subprocess.CalledProcessError as e:
        logger.exception(
            'provider_link_failed',
            provider=provider_name,
            error=str(e),
        )
        return 1
    except FileNotFoundError:
        logger.exception(
            'provider_cli_not_found',
            provider=provider_name,
            command=provider_config.cli,
        )
        return 1

    # Create additional symlinks if configured
    if provider_config.symlinks:
        symlinks_dict = [{'source': str(s.source), 'target': str(s.target)} for s in provider_config.symlinks]
        create_provider_symlinks(
            provider_name,
            cli_info,
            symlinks_dict,
        )

    return 0


def _get_provider_names(config: 'RepolishConfig') -> list[str]:
    """Get list of provider names in the correct order.

    Args:
        config: Repolish configuration

    Returns:
        List of provider names to process
    """
    if config.providers_order:
        return config.providers_order
    # If no order specified, use all providers in arbitrary order
    return list(config.providers.keys())


def run(argv: list[str]) -> int:
    """Run repolish-link with argv-like list and return an exit code.

    This is separated from `main()` so we can keep `main()` small and
    maintain a low cyclomatic complexity for the top-level entrypoint.
    """
    parser = argparse.ArgumentParser(
        prog='repolish-link',
        description='Link provider resources to the project',
    )
    add_verbosity_argument(parser)
    parser.add_argument(
        '--config',
        dest='config',
        type=Path,
        default=Path('repolish.yaml'),
        help='Path to the repolish YAML configuration file',
    )
    args = parser.parse_args(argv)
    config_path = args.config

    # Configure logging using resolved verbosity (supports CI auto-detection)
    verbosity = resolve_verbosity(args)
    configure_logging(verbosity=verbosity)

    logger.info(
        'loading_config',
        config_file=str(config_path),
        _display_level=1,
    )
    config = load_config(config_path, validate=False)

    if not config.providers:
        logger.warning('no_providers_configured', _display_level=1)
        return 0

    provider_names = _get_provider_names(config)
    logger.info(
        'linking_providers',
        providers=provider_names,
        _display_level=1,
    )

    # Process each provider
    for provider_name in provider_names:
        if provider_name not in config.providers:
            logger.warning(
                'provider_not_found_in_order',
                provider=provider_name,
                _display_level=1,
            )
            continue

        provider_config = config.providers[provider_name]
        exit_code = _process_single_provider(provider_name, provider_config)
        if exit_code != 0:
            return exit_code

    logger.info('all_providers_linked', _display_level=1)
    return 0


def main() -> int:
    """Main entry point for the repolish-link CLI.

    This function keeps a very small surface area and delegates the work to
    `run()`. High-level error handling lives here so callers (and tests) get
    stable exit codes.
    """
    try:
        return run(sys.argv[1:])
    except SystemExit:
        raise
    except FileNotFoundError as e:
        logger.exception('config_not_found', error=str(e))
        return 1
    except Exception:  # pragma: no cover - high level CLI error handling
        logger.exception('failed_to_run_repolish_link')
        return 1


if __name__ == '__main__':
    sys.exit(main())
