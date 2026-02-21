from typing import cast

from repolish.loader.models import Provider as _ProviderBase


def process_anchors(
    provider: _ProviderBase,
    merged_context: dict[str, object],
    merged_anchors: dict[str, str],
) -> None:
    """Resolve anchors for a provider and merge into `merged_anchors`.

    `provider` must be a ``Provider`` instance (e.g. ``ModuleProviderAdapter``).
    """
    inst = cast('_ProviderBase', provider)

    val = inst.create_anchors(merged_context)
    if not val:
        return
    if not isinstance(val, dict):
        msg = 'create_anchors() must return a dict'
        raise TypeError(msg)
    merged_anchors.update(cast('dict[str, str]', val))
    return
