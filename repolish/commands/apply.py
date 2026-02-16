from pathlib import Path

from hotlog import get_logger

from repolish.builder import create_cookiecutter_template
from repolish.config import load_config
from repolish.cookiecutter import (
    apply_generated_output,
    build_final_providers,
    check_generated_output,
    prepare_staging,
    preprocess_templates,
    render_template,
    rich_print_diffs,
)
from repolish.utils import run_post_process
from repolish.version import __version__

logger = get_logger(__name__)


def command(config_path: Path, *, check_only: bool) -> int:
    """Run repolish with the given config and options."""
    # Logging is already configured in the callback

    # Log the running version early so CI logs always show which repolish wrote the output
    logger.info('running_repolish', version=__version__)

    config = load_config(config_path)

    providers = build_final_providers(config)
    logger.info(
        'final_providers_generated',
        template_directories=[str(d) for d in config.directories],
        context=providers.context,
        delete_paths=[p.as_posix() for p in providers.delete_files],
        delete_history={
            key: [{'source': d.source, 'action': d.action.value} for d in decisions]
            for key, decisions in providers.delete_history.items()
        },
    )

    # Prepare staging and template
    base_dir, setup_input, setup_output = prepare_staging(config)

    template_dirs = [Path(p) for p in config.directories]

    create_cookiecutter_template(setup_input, template_dirs)

    # Preprocess templates (anchor-driven replacements)
    preprocess_templates(setup_input, providers, config, base_dir)

    # Render once using cookiecutter
    render_template(setup_input, providers, setup_output)

    # Run any configured post-processing commands (formatters, linters, etc.)
    # Run them in the generated output directory so tools operate on the files
    # that will be checked or applied. If a command fails, surface an error
    # and exit non-zero so CI will fail.
    # run post_process within the rendered project folder inside setup_output
    project_folder = str(providers.context.get('_repolish_project', 'repolish'))
    post_cwd = setup_output / project_folder
    try:
        run_post_process(config.post_process, post_cwd)
    except Exception:  # pragma: no cover - error path exercised indirectly
        logger.exception('post_process_failed')
        return 3

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
