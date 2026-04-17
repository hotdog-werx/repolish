from pathlib import Path

from repolish.builder import stage_templates
from repolish.config import RepolishConfig
from repolish.config.models.provider import ResolvedProviderInfo
from repolish.misc import is_conditional_file
from repolish.providers.models import TemplateMapping


def collect_mapped_sources(
    file_mappings: dict[str, str | TemplateMapping],
) -> set[str]:
    """Return the set of source template paths explicitly claimed by `file_mappings`.

    When a provider maps a source template via `create_file_mappings`, that
    template must not also be auto-staged at its natural position in the
    provider tree — the developer has already decided where it goes (and
    possibly under a different destination name).
    """
    result: set[str] = set()
    for src in file_mappings.values():
        if isinstance(src, str):
            result.add(src)
        elif src.source_template is not None:
            result.add(src.source_template)
    return result


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
    mapped_sources: set[str] | None = None,
    workspace_mode: str | None = None,
) -> dict[str, str]:
    """Stage all provider templates into `setup_input`.

    Returns a mapping from each merged-template relative path to the provider
    alias that supplied it.

    When `workspace_mode` is provided, each provider's mode-specific overlay
    directory (``provider_root/{workspace_mode}/``) is staged after its base
    ``repolish/`` templates, allowing providers to keep mode-specific files in
    separate directories without ``create_file_mappings`` boilerplate.
    """
    template_dirs = _gather_template_directories(config)
    result = stage_templates(
        setup_input,
        template_dirs,
        template_overrides=config.template_overrides,
        mapped_sources=mapped_sources,
        workspace_mode=workspace_mode,
    )
    if isinstance(result, tuple) and len(result) == 2:
        _, sources = result
    else:
        sources = {}
    return sources


def _unmapped_in_dir(
    alias: str,
    repolish_dir: Path,
    mapped_sources: set[str],
) -> list[tuple[str, str]]:
    """Return (alias, template_path) pairs for unmapped conditional files in *repolish_dir*."""
    issues: list[tuple[str, str]] = []
    for item in repolish_dir.rglob('*'):
        if not item.is_file():
            continue
        rel = item.relative_to(repolish_dir).as_posix()
        stripped = rel.removesuffix('.jinja')
        if is_conditional_file(rel) and stripped not in mapped_sources:
            issues.append((alias, stripped))
    return issues


def find_unmapped_conditional_sources(
    provider_infos: dict[str, ResolvedProviderInfo],
    mapped_sources: set[str],
) -> list[tuple[str, str]]:
    """Return (alias, template_path) pairs for unmapped ``_repolish.*`` files.

    Scans each provider's ``repolish/`` template tree for files whose names
    start with the ``_repolish.`` prefix but that are not referenced by any
    ``create_file_mappings`` value (i.e. not in *mapped_sources*).  These
    are likely forgotten mapping sources — template files added to the
    provider but never wired up to a destination.

    Used by the lint pass to surface potential omissions before they
    silently disappear from the staging area (the apply pass skips them).
    """
    issues: list[tuple[str, str]] = []
    for alias, info in provider_infos.items():
        repolish_dir = info.provider_root / 'repolish'
        if repolish_dir.is_dir():
            issues.extend(_unmapped_in_dir(alias, repolish_dir, mapped_sources))
    return issues
