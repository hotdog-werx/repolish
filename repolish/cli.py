import argparse
from pathlib import Path

from hotlog import configure_logging, get_logger

from .config import load_config
from .loader import create_context

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='repolish')

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

    args = parser.parse_args(argv)
    check_only = args.check
    config_path = args.config

    configure_logging()

    try:
        config = load_config(config_path)
    except Exception:  # pragma: no cover - high level CLI error handling
        logger.exception('failed_to_load_config')
        return 1

    context = {**create_context(config.directories), **config.context}
    logger.info(
        'context_generated',
        config_directories=config.directories,
        context=context,
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
