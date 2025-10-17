from pathlib import Path
from textwrap import dedent

import pytest


@pytest.fixture
def temp_repolish_dirs(tmp_path: Path) -> list[str]:
    """Create temporary directories with valid repolish.py files."""
    # Create first directory with repolish.py
    dir1 = tmp_path / 'template1'
    dir1.mkdir()
    repolish_py1 = dir1 / 'repolish.py'
    (dir1 / 'repolish').mkdir(parents=True, exist_ok=True)
    repolish_py1.write_text(
        dedent("""
        def create_context():
            return {
                "name": "Template1",
                "version": "1.0",
                "author": "Test Author",
                "language": "will be overridden"
            }
    """),
    )

    # Create second directory with repolish.py
    dir2 = tmp_path / 'template2'
    dir2.mkdir()
    repolish_py2 = dir2 / 'repolish.py'
    (dir2 / 'repolish').mkdir(parents=True, exist_ok=True)
    repolish_py2.write_text(
        dedent("""
        def create_context():
            return {
                "description": "A test template",
                "license": "MIT",
                "year": 2023
            }
    """),
    )

    # Create third directory with repolish.py
    dir3 = tmp_path / 'template3'
    dir3.mkdir()
    repolish_py3 = dir3 / 'repolish.py'
    (dir3 / 'repolish').mkdir(parents=True, exist_ok=True)
    repolish_py3.write_text(
        dedent("""
        def create_context():
            return {
                "framework": "pytest",
                "language": "python"
            }
    """),
    )

    return [str(dir1), str(dir2), str(dir3)]
