from pathlib import Path, PurePosixPath

from repolish.loader import FileMode, TemplateMapping


def process_create_only_files(
    mappings: dict[str, str | TemplateMapping],
    create_only_set: set[Path],
) -> None:
    """Process provider `create_only` contributions from precomputed mapping.

    `mappings` should come from `provider.create_file_mappings()`.  Any
    entries annotated with `FileMode.CREATE_ONLY` are added to
    `create_only_set`.
    """
    for k, v in mappings.items():
        if isinstance(v, TemplateMapping) and v.file_mode == FileMode.CREATE_ONLY:
            create_only_set.add(Path(*PurePosixPath(k).parts))
