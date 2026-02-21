from pathlib import Path

from repolish.loader.models import Provider as _ProviderBase
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
    provider: _ProviderBase,
    context: object,
    accum: Accumulators,
) -> None:
    """Process a provider's file mapping contributions and merge.

    The provider instance is already available; no module dict is required.
    """
    fm = provider.create_file_mappings(context)
    if not isinstance(fm, dict):
        return

    for k, v in fm.items():
        _process_mapping_item(k, v, provider_id, accum)
