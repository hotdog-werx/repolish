import argparse
import sys
from pathlib import Path

from hotlog import (
    add_verbosity_argument,
    configure_logging,
    get_logger,
    resolve_verbosity,
)

from .config import load_config
from .cookiecutter import (
    apply_generated_output,
    build_final_providers,
    check_generated_output,
    prepare_staging,
    prepare_template,
    preprocess_templates,
    render_template,
    rich_print_diffs,
)
from .utils import run_post_process
from .version import __version__

logger = get_logger(__name__)


def run(argv: list[str]) -> int:
    """Run repolish with argv-like list and return an exit code.

    This is separated from `main()` so we can keep `main()` small and
    maintain a low cyclomatic complexity for the top-level entrypoint.
    """
    parser = argparse.ArgumentParser(prog='repolish')
    # add standard verbosity switch provided by hotlog
    add_verbosity_argument(parser)

    parser.add_argument(
        '--check',
        dest='check',
        action='store_true',
        help='Load config and create context (dry-run check)',
    )
    parser.add_argument(
        '--config',
        dest='config',
        type=Path,
        default=Path('repolish.yaml'),
        help='Path to the repolish YAML configuration file',
    )
    parser.add_argument('--version', action='version', version=__version__)
    args = parser.parse_args(argv)
    check_only = args.check
    config_path = args.config

    # Configure logging using resolved verbosity (supports CI auto-detection)
    verbosity = resolve_verbosity(args)
    configure_logging(verbosity=verbosity)

    # Log the running version early so CI logs always show which repolish wrote the output
    logger.info('running_repolish', version=__version__)

    config = load_config(config_path)

    providers = build_final_providers(config)
    logger.info(
        'final_providers_generated',
        template_directories=config.directories,
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
    prepare_template(setup_input, template_dirs)

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
                suggestion='run `repolish` to apply changes',
            )
            rich_print_diffs(diffs)
        return 2 if diffs else 0

    # apply into project
    apply_generated_output(setup_output, providers, base_dir)
    return 0


def main() -> int:
    """Main entry point for the repolish CLI.

    This function keeps a very small surface area and delegates the work to
    `run()`. High-level error handling lives here so callers (and tests) get
    stable exit codes.
    """
    try:
        # Forward the real command-line arguments so flags like --version work.
        return run(sys.argv[1:])
    except SystemExit:
        raise
    except Exception:  # pragma: no cover - high level CLI error handling
        logger.exception('failed_to_run_repolish')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
