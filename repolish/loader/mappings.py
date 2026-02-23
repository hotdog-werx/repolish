from pathlib import Path
from typing import cast

from repolish.loader.types import Accumulators, FileMode, TemplateMapping


def _process_mapping_item(
    k: str,
    v: object,
    provider_id: str,
    accum: Accumulators,
) -> None:
    """Process a single mapping entry and mutate the provided accumulators."""
    if v is None:
        return

    if isinstance(v, str):
        accum.merged_file_mappings[k] = v
        return

    if isinstance(v, TemplateMapping):
        annotated = TemplateMapping(
            source_template=v.source_template,
            extra_context=v.extra_context,
            file_mode=v.file_mode,
            source_provider=provider_id,
        )

        if annotated.file_mode == FileMode.DELETE:
            accum.delete_set.add(Path(k))
            accum.merged_file_mappings.pop(k, None)
            return

        if annotated.file_mode == FileMode.CREATE_ONLY:
            accum.create_only_set.add(Path(k))

        accum.merged_file_mappings[k] = annotated
        return


def process_file_mappings(
    provider_id: str,
    mappings: dict[str, str | TemplateMapping] | object,
    accum: Accumulators,
) -> None:
    """Merge a precomputed mapping dictionary into the accumulators.

    Previously this helper accepted a :class:`Provider` instance and a
    context object, calling ``provider.create_file_mappings()`` internally.
    The extra indirection forced callers to invoke that method multiple times
    when they only needed its result.  By switching to a simple ``mappings``
    argument we avoid redundant calls and make the helper easier to test and
    future-proof against removal of the module adapter.
    """
    if not isinstance(mappings, dict):
        # defensive - callers should normally supply a dict, but the adapter
        # layer ensures this is safe even if the provider misbehaves.
        return

    # narrow the view to a str-keyed dict for the type checker; at runtime
    # the cast is a no-op because we already know ``mappings`` is a dict.
    for k, v in cast('dict[str, object]', mappings).items():
        _process_mapping_item(k, v, provider_id, accum)
