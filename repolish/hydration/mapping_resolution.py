from dataclasses import dataclass

from repolish.hydration.misc import get_source_str_from_mapping
from repolish.providers import SessionBundle, TemplateMapping


@dataclass
class MappingResolution:
    """Normalized mapping and file-set view used across hydration stages.

    This structure centralizes how mappings are interpreted so each stage
    (preprocess, render, compare, apply) can consume the same resolved view
    instead of rebuilding equivalent sets locally.
    """

    source_to_dest: dict[str, str]
    dest_to_source: dict[str, str]
    regular_mappings: dict[str, str | TemplateMapping]
    promoted_mappings: dict[str, str | TemplateMapping]
    mapped_sources: set[str]
    regular_dests: set[str]
    promoted_dests: set[str]
    paused_dests: frozenset[str]
    suppressed_sources: set[str]
    create_only_dests: set[str]
    delete_dests: set[str]


def _collect_source_maps(
    providers: SessionBundle,
) -> tuple[dict[str, str], dict[str, str], set[str]]:
    """Build source and destination lookup maps from all mapping dictionaries."""
    source_to_dest: dict[str, str] = {}
    dest_to_source: dict[str, str] = {}
    mapped_sources: set[str] = set()

    def _add_mappings(mappings: dict[str, str | TemplateMapping]) -> None:
        for dest, source in mappings.items():
            source_str = get_source_str_from_mapping(source)
            if source_str is None:
                continue
            # Preserve existing precedence used in preprocessing where promoted
            # mappings are merged after regular mappings.
            source_to_dest[source_str] = dest
            dest_to_source[dest] = source_str
            mapped_sources.add(source_str)

    _add_mappings(providers.file_mappings)
    _add_mappings(providers.promoted_file_mappings)

    return source_to_dest, dest_to_source, mapped_sources


def resolve_mappings(providers: SessionBundle) -> MappingResolution:
    """Return a single normalized mapping view for hydration pipelines."""
    source_to_dest, dest_to_source, mapped_sources = _collect_source_maps(
        providers,
    )
    create_only_dests = {path.as_posix() for path in providers.create_only_files}
    delete_dests = {path.as_posix() for path in providers.delete_files}

    return MappingResolution(
        source_to_dest=source_to_dest,
        dest_to_source=dest_to_source,
        regular_mappings=providers.file_mappings,
        promoted_mappings=providers.promoted_file_mappings,
        mapped_sources=mapped_sources,
        regular_dests=set(providers.file_mappings.keys()),
        promoted_dests=set(providers.promoted_file_mappings.keys()),
        paused_dests=providers.paused_files,
        suppressed_sources=set(providers.suppressed_sources),
        create_only_dests=create_only_dests,
        delete_dests=delete_dests,
    )
