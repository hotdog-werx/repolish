from pathlib import Path, PurePosixPath
from typing import cast

from repolish.loader.types import FileMode, TemplateMapping


def process_create_only_files(
    mappings: dict[str, str | TemplateMapping] | object,
    create_only_set: set[Path],
) -> None:
    """Process provider `create_only` contributions from precomputed mapping.

    ``mappings`` should come from ``provider.create_file_mappings()``.  Any
    entries annotated with ``FileMode.CREATE_ONLY`` are added to
    ``create_only_set``.
    """
    if not isinstance(mappings, dict):
        return

    for k, v in mappings.items():
        if isinstance(v, TemplateMapping) and v.file_mode == FileMode.CREATE_ONLY:
            # ``mappings`` is a ``dict`` but not generically typed at runtime;
            # cast the key to ``str`` so the path constructor is happy.
            key = cast('str', k)
            create_only_set.add(Path(*PurePosixPath(key).parts))
