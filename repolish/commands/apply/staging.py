from pathlib import Path

from repolish.builder import stage_templates
from repolish.config import RepolishConfig
from repolish.providers.models import TemplateMapping


def collect_excluded_sources(
    file_mappings: dict[str, str | TemplateMapping],
) -> set[str]:
    """Return the set of source template paths explicitly claimed by `file_mappings`.

    When a provider maps a source template via `create_file_mappings`, that
    template must not also be auto-staged at its natural position in the
    provider tree — the developer has already decided where it goes (and
    possibly under a different destination name).
    """
    excluded: set[str] = set()
    for src in file_mappings.values():
        if isinstance(src, str):
            excluded.add(src)
        elif src.source_template is not None:
            excluded.add(src.source_template)
    return excluded


def _gather_template_directories(
    config: RepolishConfig,
) -> list[Path | tuple[str | None, Path]]:
    """Return provider template directories in staged order.

    Internal helper for `create_staged_template`. Respects `providers_order`
    when set, otherwise uses config dict key order.
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


def create_staged_template(
    setup_input: Path,
    config: RepolishConfig,
    excluded_sources: set[str] | None = None,
) -> dict[str, str]:
    """Stage all provider templates into `setup_input`.

    Returns a mapping from each merged-template relative path to the provider
    alias that supplied it.
    """
    template_dirs = _gather_template_directories(config)
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
