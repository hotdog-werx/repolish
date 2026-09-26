"""Quarantine for the ``cli:`` provider registration mechanism.

Everything that shells out to a provider's link CLI lives in
:mod:`repolish.cli_registry.bridge`; the v2 removal deletes this package
together with the ``cli:`` config field and the branch points that call
into it. Module-declared providers never import this package.
"""

from repolish.cli_registry.bridge import (
    probe_provider_info,
    run_provider_link,
)

__all__ = [
    'probe_provider_info',
    'run_provider_link',
]
