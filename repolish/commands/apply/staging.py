from pathlib import Path

from repolish.builder import stage_templates
from repolish.config import RepolishConfig
from repolish.loader.models import TemplateMapping


def _collect_excluded_sources(
    file_mappings: dict[str, str | TemplateMapping],
) -> set[str]:
    """Collect all explicit source template paths from file_mappings.

    When a provider explicitly maps a source template via ``create_file_mappings``,
    that file should not also be auto-staged at its natural position in the
    provider's ``repolish/`` tree — the developer has already decided where it
    goes (possibly with a different destination name).
    """
    excluded: set[str] = set()
    for src in file_mappings.values():
        if isinstance(src, str):
            excluded.add(src)
        elif src.source_template is not None:
            excluded.add(src.source_template)
    return excluded


def gather_template_directories(
    config: RepolishConfig,
) -> list[Path | tuple[str | None, Path]]:
    """Return the template directories in the order they should be staged.

    Providers drive the result; the `directories` field no longer exists.
    If `providers_order` is given we honour it, otherwise we use dict key order.
    The return type uses the same element-level union as
    :func:`stage_templates` so type checks won't complain about invariant lists.
    """
    template_dirs: list[Path | tuple[str | None, Path]] = []
    order = config.providers_order or list(config.providers.keys())
    for alias in order:
        info = config.providers.get(alias)
        if info is None:
            continue
        path = info.provider_root
        template_dirs.append((alias, path))

    if not any(isinstance(entry, tuple) and entry[0] is not None for entry in template_dirs):
        return [entry if isinstance(entry, Path) else entry[1] for entry in template_dirs]

    return template_dirs


def _create_staged_template(
    setup_input: Path,
    config: RepolishConfig,
    excluded_sources: set[str] | None = None,
) -> dict[str, str]:
    """Build template directory list from `config` and stage into `setup_input`.

    Returns a mapping from merged-template-relative-path to the provider alias
    that supplied it.
    """
    template_dirs = gather_template_directories(config)
    result = stage_templates(
        setup_input,
        template_dirs,
        template_overrides=config.template_overrides,
        excluded_sources=excluded_sources,
    )
    if isinstance(result, tuple) and len(result) == 2:
        _, sources = result
    else:
        sources = {}
    return sources
