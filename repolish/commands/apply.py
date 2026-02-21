from pathlib import Path

from hotlog import get_logger

from repolish.builder import create_cookiecutter_template
from repolish.config import load_config
from repolish.config.models import RepolishConfig
from repolish.cookiecutter import (
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
from repolish.misc import ctx_to_dict
from repolish.utils import run_post_process
from repolish.version import __version__

logger = get_logger(__name__)


def _create_staged_template(setup_input: Path, config: RepolishConfig) -> None:
    """Build template directory list from `config` and create staging.

    This mirrors the previous inline logic in `command` but keeps the
    complexity outside of the top-level function.
    """
    template_dirs = _gather_template_directories(config)
    create_cookiecutter_template(
        setup_input,
        template_dirs,
        template_overrides=config.template_overrides,
    )


def _gather_template_directories(
    config: RepolishConfig,
) -> list[Path] | list[tuple[str | None, Path]]:
    """Return the template directories in the order they should be staged.

    When provider metadata is present this returns a list of ``(alias, Path)``
    tuples. Otherwise a plain list of ``Path`` objects is returned for legacy
    compatibility.
    """
    if not config.providers_order:
        return [Path(p) for p in config.directories]

    template_dirs: list[tuple[str | None, Path]] = []
    for alias in config.providers_order:
        info = config.providers.get(alias)
        if info is None:
            continue
        path = info.target_dir / info.templates_dir
        template_dirs.append((alias, path))

    for p in config.directories:
        if not any(str(p) == str(d) for _, d in template_dirs):
            template_dirs.append((None, Path(p)))

    return template_dirs


def command(config_path: Path, *, check_only: bool) -> int:
    """Run repolish with the given config and options."""
    # Logging is already configured in the callback

    # Log the running version early so CI logs always show which repolish wrote the output
    logger.info('running_repolish', version=__version__)

    config = load_config(config_path)

    providers = build_final_providers(config)

    # build a more detailed context payload for the log event.  non-migrated
    # providers receive the merged context with migrated keys removed; migrated
    # providers render using their own captured contexts, which we emit under
    # their alias so the log shows exactly what each new-style provider will
    # supply.  un-migrated providers are grouped under ``non_migrated``; when
    # there are none this will be an empty dict.
    non_migrated_ctx = _compute_merged_context(providers)

    migrated_ctxs: dict[str, dict[str, object]] = {}
    for pid, migrated in providers.provider_migrated.items():
        if not migrated:
            continue
        migrated_ctxs[pid] = ctx_to_dict(providers.provider_contexts.get(pid))

    logger.info(
        'final_providers_generated',
        template_directories=[str(d) for d in config.directories],
        # new structure for context makes it clear what each provider sees
        context={'non_migrated': non_migrated_ctx, 'migrated': migrated_ctxs},
        delete_paths=[p.as_posix() for p in providers.delete_files],
        delete_history={
            key: [{'source': d.source, 'action': d.action.value} for d in decisions]
            for key, decisions in providers.delete_history.items()
        },
    )

    # Prepare staging and template
    base_dir, setup_input, setup_output = prepare_staging(config)
    _create_staged_template(setup_input, config)

    # Preprocess templates (anchor-driven replacements)
    preprocess_templates(setup_input, providers, config, base_dir)

    # Render once (cookiecutter by default; can opt-out via config.no_cookiecutter)
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
