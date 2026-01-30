import argparse
from pathlib import Path

import yaml
from hotlog import (
    add_verbosity_argument,
    configure_logging,
    get_logger,
    resolve_verbosity,
)
from rich.console import Console

from .processors import replace_text

logger = get_logger(__name__)


def main() -> int:
    """Main entry point for the repolish-debugger CLI."""
    parser = argparse.ArgumentParser(prog='repolish-debugger')
    add_verbosity_argument(parser)

    parser.add_argument(
        'debug_file',
        type=Path,
        help='Path to the YAML debug configuration file',
    )
    parser.add_argument(
        '--show-patterns',
        action='store_true',
        help='Show extracted patterns from template',
    )
    parser.add_argument(
        '--show-steps',
        action='store_true',
        help='Show intermediate processing steps',
    )

    args = parser.parse_args()

    # Configure logging
    verbosity = resolve_verbosity(args)
    configure_logging(verbosity=verbosity)

    return run_debug(args.debug_file, args.show_patterns, args.show_steps)


def run_debug(debug_file: Path, show_patterns: bool, show_steps: bool) -> int:
    """Run the debug preprocessor tool."""
    console = Console()

    try:
        with open(debug_file, encoding='utf-8') as f:
            debug_config = yaml.safe_load(f)
    except Exception as e:
        logger.error(
            'failed_to_load_debug_config',
            file=str(debug_file),
            error=str(e),
        )
        return 1

    if 'template' not in debug_config:
        logger.error('debug_config_missing_template')
        return 1

    template = debug_config['template']
    target = debug_config.get('target', '')
    config_data = debug_config.get('config', {})

    # Extract anchors from config
    anchors = config_data.get('anchors', {})

    console.rule('[bold]Debug Preprocessing')
    logger.info(
        'debug_preprocessing_started',
        template_length=len(template),
        target_length=len(target),
        anchors=list(anchors.keys()),
    )
    console.print()

    if show_patterns:
        from .processors import extract_patterns

        patterns = extract_patterns(template)
        console.rule('[bold]Extracted Patterns')
        logger.info(
            'extracted_patterns',
            tag_blocks=patterns.tag_blocks,
            regexes=patterns.regexes,
        )
        console.print()

    try:
        result = replace_text(template, target, anchors_dictionary=anchors)
        if show_steps:
            console.rule('[bold]Processing Steps')
            # We could add more detailed step-by-step output here
            logger.info(
                'processing_steps',
                steps=['anchor_replacements', 'regex_transformations'],
            )
            console.print()
        console.rule('[bold]Result')
        console.print(result)
        return 0
    except Exception as e:
        logger.exception('debug_preprocessing_failed', error=str(e))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
