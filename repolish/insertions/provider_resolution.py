"""Provider ownership resolution for insertion blocks and functions.

This module provides the canonical logic for determining which provider
"owns" a given insertion block or function based on naming conventions:

- Qualified names (e.g., 'alpha:display-year') belong to that specific provider
- Unqualified names belong to the first provider for a file (fallback owner)

All provider filtering across repolish should use these functions to ensure
consistent behavior.
"""

from __future__ import annotations

from typing import TypeVar

T = TypeVar('T')


def is_provider_owner(
    identifier: str,
    provider_alias: str,
    *,
    is_first_provider: bool = False,
) -> bool:
    """Check if an identifier belongs to a specific provider.

    An identifier (function name or block tag) belongs to a provider if:
    - It's provider-qualified with this provider's alias (e.g., 'alpha:display-year')
    - It's unqualified and this provider is the first one (owns the fallback)

    Args:
        identifier: The function name or block tag to check
        provider_alias: The provider's alias (e.g., 'alpha')
        is_first_provider: Whether this provider is the first for the file

    Returns:
        True if the identifier belongs to this provider, False otherwise
    """
    if ':' in identifier:
        return identifier.startswith(f'{provider_alias}:')
    return bool(is_first_provider)


def resolve_provider_function_name(
    key: str,
    provider_alias: str,
    *,
    is_first_provider: bool,
) -> str | None:
    """Resolve a registry key to a provider-visible function name.

    This determines what function name a provider should see based on
    ownership rules. Returns None if the key doesn't belong to this provider.

    Args:
        key: The registry key (may be qualified or unqualified)
        provider_alias: The provider's alias (e.g., 'alpha')
        is_first_provider: Whether this provider is the first for the file

    Returns:
        The function name this provider should see, or None if not owned
    """
    if is_provider_owner(
        key,
        provider_alias,
        is_first_provider=is_first_provider,
    ):
        if key.startswith(f'{provider_alias}:'):
            return key.split(':', 1)[1]
        return key
    return None
