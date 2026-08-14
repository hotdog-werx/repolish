#!/usr/bin/env python
"""Pre-build provider wheels for integration tests.

Run this before running tests to avoid build overhead during test execution.

Usage:
    python tests/integration/prebuild_providers.py
    pytest tests/integration -n auto
"""

import subprocess
from pathlib import Path

EXAMPLES_DIR = Path(__file__).parent.parent.parent / 'provider-examples'
DIST_DIR = EXAMPLES_DIR / '.dist'

PROVIDERS = [
    'simple-provider',
    'scaffold-provider',
    'devkit/python',
    'devkit/workspace',
]


def main():
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    for provider in PROVIDERS:
        subprocess.run(  # noqa: S603 - controlled testing
            ['uv', 'build', '--wheel', '--out-dir', str(DIST_DIR)],  # noqa: S607 - controlled testing
            cwd=str(EXAMPLES_DIR / provider),
            check=True,
        )


if __name__ == '__main__':
    main()
