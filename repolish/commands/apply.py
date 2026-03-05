from pathlib import Path

from hotlog import get_logger

from repolish.builder import create_cookiecutter_template
from repolish.config import RepolishConfig, load_config
from repolish.hydration import (
    apply_generated_output,
    build_final_providers,
    check_generated_output,
    prepare_staging,
    preprocess_templates,
    render_template,
    rich_print_diffs,
)

# use rendering helper to compute the merged context used by non-migrated
# providers; importing the private function is fine since it lives in the
# same package and keeps the algorithm in one place.
from repolish.hydration.rendering import _compute_merged_context
from repolish.loader.models import Providers
from repolish.misc import ctx_to_dict
from repolish.utils import run_post_process
from repolish.version import __version__

logger = get_logger(__name__)


def _create_staged_template(
    setup_input: Path,
    config: RepolishConfig,
) -> dict[str, str]:
    """Build template directory list from `config` and create staging.

    This mirrors the previous inline logic in `command` but keeps the
    complexity outside of the top-level function.

    Returns:
        A mapping from merged-template-relative-path to the provider id that
        supplied it.  Tests previously patched `create_cookiecutter_template`
        and expected no return value; to keep them working we normalise the
        result here.
    """
    template_dirs = _gather_template_directories(config)
    result = create_cookiecutter_template(
        setup_input,
        template_dirs,
        template_overrides=config.template_overrides,
    )
    # result may be either Path (legacy) or (Path, sources) tuple
    if isinstance(result, tuple) and len(result) == 2:
        _, sources = result
    else:
        sources = {}
    return sources


def _gather_template_directories(
    config: RepolishConfig,
) -> list[Path] | list[tuple[str | None, Path]]:
    """Return the template directories in the order they should be staged.

    Providers drive the result; the `directories` field no longer exists.
    If `providers_order` is given we honour it, otherwise we use dict key order.
    The return type matches the previous helper so callers remain unchanged.
    """
    template_dirs: list[tuple[str | None, Path]] = []
    # build in-order list from providers
    order = config.providers_order or list(config.providers.keys())
    for alias in order:
        info = config.providers.get(alias)
        if info is None:
            continue
        path = info.target_dir
        template_dirs.append((alias, path))

    # if no alias information needed, return simple Paths
    if not any(alias is not None for alias, _ in template_dirs):
        return [path for _, path in template_dirs]

    return template_dirs


def _compute_migrated_list(
    config: RepolishConfig,
    providers: Providers,
) -> list[dict[str, object]]:
    """Return an ordered list of migrated provider contexts.

    Each entry includes the provider alias (if known), the template directory
    used as the loader provider id, and the context that provider captured.
    The ordering respects `config.providers_order` when provided, and then
    appends any other migrated providers.
    """
    # build quick lookups to avoid nested loops
    pid_to_alias: dict[str, str] = {}
    for alias, info in config.providers.items():
        pid_to_alias[info.target_dir.as_posix()] = alias

    def pid_for_alias(alias: str) -> str | None:
        return pid_to_alias.get(alias)

    result: list[dict[str, object]] = []
    seen: set[str] = set()

    # honour explicit ordering first
    for alias in config.providers_order or []:
        pid = pid_for_alias(alias)
        if not pid or not providers.provider_migrated.get(pid):
            continue
        result.append(
            {
                'alias': alias,
                'directory': pid,
                'context': ctx_to_dict(providers.provider_contexts.get(pid)),
            },
        )
        seen.add(pid)

    # then add any migrated providers not yet recorded
    for pid, migrated in providers.provider_migrated.items():
        if not migrated or pid in seen:
            continue
        alias = pid_to_alias.get(pid)
        result.append(
            {
                'alias': alias,
                'directory': pid,
                'context': ctx_to_dict(providers.provider_contexts.get(pid)),
            },
        )

    return result


def _log_final_providers_event(
    config: RepolishConfig,
    providers: Providers,
    non_migrated_ctx: dict[str, object],
    migrated_list: list[dict[str, object]],
) -> None:
    """Emit the `final_providers_generated` logger event.

    Extracts fields from `config` and `providers` to keep the call site
    concise.
    """
    logger.info(
        'final_providers_generated',
        template_directories=[str(p[1] if isinstance(p, tuple) else p) for p in _gather_template_directories(config)],
        # we now split context into a single global bucket and a provider list
        context={
            'global_context': non_migrated_ctx,
            'providers': migrated_list,
        },
        delete_paths=[p.as_posix() for p in providers.delete_files],
        delete_history={
            key: [{'source': d.source, 'action': d.action.value} for d in decisions]
            for key, decisions in providers.delete_history.items()
        },
    )


def command(config_path: Path, *, check_only: bool) -> int:
    """Run repolish with the given config and options."""
    # Logging is already configured in the callback

    # Log the running version early so CI logs always show which repolish wrote the output
    logger.info('running_repolish', version=__version__)

    config = load_config(config_path)
    providers = build_final_providers(config)

    # compute contexts for logging
    non_migrated_ctx = _compute_merged_context(providers)
    migrated_list = _compute_migrated_list(config, providers)
    _log_final_providers_event(
        config,
        providers,
        non_migrated_ctx,
        migrated_list,
    )

    # Prepare staging and template
    base_dir, setup_input, setup_output = prepare_staging(config)
    sources = _create_staged_template(setup_input, config)
    # attach file provenance map so rendering can pick per-file context
    providers.template_sources = sources

    # Preprocess templates (anchor-driven replacements)
    preprocess_templates(setup_input, providers, config, base_dir)

    # Render templates using Jinja2 (cookiecutter support removed).
    render_template(setup_input, providers, setup_output, config)

    # Run any configured post-processing commands (formatters, linters, etc.)
    # Run them in the generated output directory so tools operate on the files
    # that will be checked or applied. If a command fails, surface an error
    # and exit non-zero so CI will fail.
    # run post_process within the rendered project folder inside setup_output
    project_folder = str(providers.context.get('_repolish_project', 'repolish'))
    post_cwd = setup_output / project_folder
    run_post_process(config.post_process, post_cwd)

    # Decide whether to check or apply generated output
    if check_only:
        diffs = check_generated_output(setup_output, providers, base_dir)
        if diffs:
            logger.error(
                'check_results',
                suggestion='run `repolish apply` to apply changes',
            )
            rich_print_diffs(diffs)
        return 2 if diffs else 0

    # apply into project
    apply_generated_output(setup_output, providers, base_dir)
    return 0
