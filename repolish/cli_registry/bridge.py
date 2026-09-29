"""The subprocess bridge to ``cli:``-declared provider link commands.

This package is the quarantine boundary for the CLI registration mechanism:
everything that shells out to a provider's link CLI lives here, and the v2
removal is exactly this package plus the ``cli:`` config field plus the
marked branch points that call into it (see
:func:`repolish.linker.health.ensure_providers_ready` and
:func:`repolish.linker.orchestrator.process_provider`). Module-declared
providers (:mod:`repolish.linker.module_link`) never touch this module.

The protocol is deliberately narrow: a ``<cli> --info`` probe reports the
provider's current package location as JSON, and the link command itself
materializes the resources under ``.repolish/``.
"""

import json
import os
import shlex
import subprocess

from hotlog import get_logger

from repolish.config.models.metadata import ProviderFileInfo

logger = get_logger(__name__)


def _link_env(location_context: str | None) -> dict[str, str]:
    """Build the subprocess env for provider link CLIs."""
    env = {**os.environ, 'REPOLISH_LINK_SUPPRESS_OUTPUT': '1'}
    if location_context:
        env['REPOLISH_LINK_CONTEXT'] = location_context
    return env


def probe_provider_info(
    link_command: str,
    *,
    location_context: str | None = None,
) -> ProviderFileInfo:
    """Ask a provider CLI where its resources currently live.

    Runs ``<cli> --info`` — the cheap half of the link protocol: no template
    copying or symlink creation happens, the CLI only reports its current
    package location.  Used to check whether a cached registration is stale
    (e.g. after switching between an installed release and a dev checkout).

    Args:
        link_command: CLI command to run (e.g., 'codeguide-link').
        location_context: Optional context string for monorepo awareness.

    Returns:
        Provider information from the ``--info`` output.

    Raises:
        subprocess.CalledProcessError: If the command fails.
    """
    cmd_parts = shlex.split(link_command)
    logger.debug('getting_provider_info', command=f'{link_command} --info')
    # S603: subprocess call is intentional - we need to call provider link CLIs
    # configured by the user (e.g., 'codeguide-link'). This is the core
    # functionality of repolish-link and the commands are from the config file.
    result = subprocess.run(  # noqa: S603
        [*cmd_parts, '--info'],
        capture_output=True,
        text=True,
        check=True,
        env=_link_env(location_context),
    )
    return ProviderFileInfo.model_validate(json.loads(result.stdout))


def run_provider_link(
    provider_name: str,
    link_command: str,
    *,
    location_context: str | None = None,
    fresh_info: ProviderFileInfo | None = None,
) -> ProviderFileInfo:
    """Run a provider's link CLI and return its info.

    Args:
        provider_name: Name of the provider
        link_command: CLI command to run (e.g., 'codeguide-link' or 'codeguide-link -v')
        location_context: Optional context string for monorepo awareness
            (e.g., 'root', 'packages/package_a'). When set, passed to the
            provider CLI via REPOLISH_LINK_CONTEXT environment variable.
        fresh_info: Info from an already-run ``--info`` probe, if any. When
            omitted the probe runs here, followed by the actual link command.

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

    cmd_parts = shlex.split(link_command)
    env = _link_env(location_context)

    provider_info = (
        fresh_info
        if fresh_info is not None
        else probe_provider_info(
            link_command,
            location_context=location_context,
        )
    )

    # Now run the actual link command
    logger.debug('running_link_command', command=link_command)
    # S603: subprocess call is intentional - see comment in probe_provider_info
    subprocess.run(  # noqa: S603
        cmd_parts,
        check=True,
        env=env,
    )

    logger.info(
        'provider_linked',
        provider=provider_name,
        target=str(provider_info.resources_dir),
        _display_level=1,
    )

    return provider_info
