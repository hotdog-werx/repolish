from typing import cast

from repolish.loader.models import Provider as _ProviderBase


def process_anchors(
    provider: _ProviderBase,
    provider_context: object,
    merged_anchors: dict[str, str],
) -> None:
    """Resolve anchors for a provider and merge into `merged_anchors`.

    `provider_context` is the provider's own context object (the same value
    passed to `create_file_mappings`).
    """
    val = provider.create_anchors(provider_context)
    if not val:
        return
    if not isinstance(val, dict):
        msg = 'create_anchors() must return a dict'
        raise TypeError(msg)
    merged_anchors.update(cast('dict[str, str]', val))
    return
