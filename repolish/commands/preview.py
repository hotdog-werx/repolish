from pathlib import Path

import yaml
from hotlog import get_logger
from pydantic import BaseModel, Field
from rich.console import Console

from repolish.preprocessors import extract_patterns, replace_text

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
    config: dict = Field(
        default_factory=dict,
        description='Configuration object with anchors and other settings',
    )


def command(
    debug_file: Path,
    *,
    show_patterns: bool,
    show_steps: bool,
) -> int:
    """Run the preview preprocessor tool."""
    console = Console()

    with Path(debug_file).open(encoding='utf-8') as f:
        data = yaml.safe_load(f)
    debug_config = DebugConfig.model_validate(data)

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
