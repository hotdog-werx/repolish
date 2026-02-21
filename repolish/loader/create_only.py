from pathlib import Path, PurePosixPath
from typing import cast

from repolish.loader.models import Provider as _ProviderBase
from repolish.loader.types import FileMode, TemplateMapping


def process_create_only_files(
    provider: _ProviderBase,
    merged_context: dict[str, object],
    create_only_set: set[Path],
) -> None:
    """Process provider `create_only` contributions and add to set.

    Accepts a *Provider* instance. Extracts any
    ``FileMode.CREATE_ONLY`` entries from ``provider.create_file_mappings()``
    and adds the destination paths to ``create_only_set``.
    """
    inst = cast('_ProviderBase', provider)

    fm = inst.create_file_mappings(merged_context)
    if not isinstance(fm, dict):
        # Not covering since this can only happen with the modules adapter.
        # which is being removed in v1. once that adapter is removed, this branch can
        # be deleted entirely.
        return  # pragma: no cover - defensive check for unexpected return type

    for k, v in fm.items():
        if isinstance(v, TemplateMapping) and v.file_mode == FileMode.CREATE_ONLY:
            create_only_set.add(Path(*PurePosixPath(k).parts))
