import argparse
from pathlib import Path
from typing import Any

import yaml
from hotlog import (
    add_verbosity_argument,
    configure_logging,
    get_logger,
    resolve_verbosity,
)
from pydantic import BaseModel, Field
from rich.console import Console

from .processors import extract_patterns, replace_text

logger = get_logger(__name__)


class DebugConfig(BaseModel):
    """Configuration for the repolish-debugger tool."""

    template: str = Field(
        ...,
        description='The template content to process',
    )
    target: str = Field(
        default='',
        description='The target file content to extract patterns from',
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description='Configuration object with anchors and other settings',
    )


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

    return run_debug(
        args.debug_file,
        show_patterns=args.show_patterns,
        show_steps=args.show_steps,
    )


def run_debug(
    debug_file: Path,
    *,
    show_patterns: bool,
    show_steps: bool,
) -> int:
    """Run the debug preprocessor tool."""
    console = Console()

    try:
        with Path(debug_file).open(encoding='utf-8') as f:
            data = yaml.safe_load(f)
        debug_config = DebugConfig.model_validate(data)
    except Exception as e:
        logger.exception(
            'failed_to_load_debug_config',
            file=str(debug_file),
            error=str(e),
        )
        return 1

    template = debug_config.template
    target = debug_config.target
    config_data = debug_config.config

    # Extract anchors from config
    anchors = config_data.get('anchors', {})

    console.rule('[bold]Debug Preprocessing')
    logger.info(
        'debug_preprocessing_started',
        template_length=len(template),
        target_length=len(target),
        anchors=[str(k) for k in anchors],
    )
    console.print()

    if show_patterns:
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
    except Exception as e:  # pragma: no cover - catch-all for unexpected errors in preprocessing
        logger.exception('debug_preprocessing_failed', error=str(e))
        return 1
    else:
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
