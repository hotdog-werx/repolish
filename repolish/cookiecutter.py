# Facade module for backward compatibility - imports are re-exported
from repolish.hydration.application import (
    _apply_file_mappings,
    _apply_regular_files,
    apply_generated_output,
)
from repolish.hydration.comparison import (
    _check_file_mappings,
    _check_regular_files,
    _check_single_file_mapping,
    _compare_and_prepare_diff,
    _preserve_line_endings,
    check_generated_output,
    collect_output_files,
)
from repolish.hydration.context import (
    _is_conditional_file,
    build_final_providers,
)
from repolish.hydration.display import rich_print_diffs
from repolish.hydration.rendering import render_template
from repolish.hydration.staging import prepare_staging, preprocess_templates

__all__ = [
    '_apply_file_mappings',
    '_apply_regular_files',
    '_check_file_mappings',
    '_check_regular_files',
    '_check_single_file_mapping',
    '_compare_and_prepare_diff',
    '_is_conditional_file',
    '_preserve_line_endings',
    'apply_generated_output',
    'build_final_providers',
    'check_generated_output',
    'collect_output_files',
    'prepare_staging',
    'preprocess_templates',
    'render_template',
    'rich_print_diffs',
]
