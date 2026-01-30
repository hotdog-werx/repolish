import argparse
import sys
from pathlib import Path

import yaml
from hotlog import add_verbosity_argument, configure_logging, resolve_verbosity

from .processors import replace_text


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
    try:
        with open(debug_file, encoding='utf-8') as f:
            debug_config = yaml.safe_load(f)
    except Exception as e:
        print(
            f'Error loading debug config from {debug_file}: {e}',
            file=sys.stderr,
        )
        return 1

    if 'template' not in debug_config:
        print(
            "Error: debug config must contain a 'template' key",
            file=sys.stderr,
        )
        return 1

    template = debug_config['template']
    target = debug_config.get('target', '')
    config_data = debug_config.get('config', {})

    # Extract anchors from config
    anchors = config_data.get('anchors', {})

    print('=== Debug Preprocessing ===')
    print(f'Template length: {len(template)}')
    print(f'Target length: {len(target)}')
    print(f'Anchors: {list(anchors.keys())}')
    print()

    if show_patterns:
        from .processors import extract_patterns

        patterns = extract_patterns(template)
        print('=== Extracted Patterns ===')
        print(f'Tag blocks: {patterns.tag_blocks}')
        print(f'Regexes: {patterns.regexes}')
        print()

    try:
        result = replace_text(template, target, anchors_dictionary=anchors)
        if show_steps:
            print('=== Processing Steps ===')
            # We could add more detailed step-by-step output here
            print('Applied anchor replacements and regex transformations')
            print()
        print('=== Result ===')
        print(result)
        return 0
    except Exception as e:
        print(f'Error during preprocessing: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
