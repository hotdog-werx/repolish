import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from repolish.cli import run

if TYPE_CHECKING:
    import pytest


def test_post_process_applies_and_fixes_file(
    tmp_path: Path,
    monkeypatch: 'pytest.MonkeyPatch',
):
    # Create a simple provider layout with a template that will be rendered
    # into the project. The template content is intentionally 'bad'.
    provider = tmp_path / 'provider'
    provider.mkdir()
    # provider must have a repolish/ directory with template files
    (provider / 'repolish').mkdir()
    templated = provider / 'repolish' / 'file.txt'
    templated.write_text('NEEDS_FORMATTING')

    # Provide a minimal repolish.py so the loader considers this a valid provider
    (provider / 'repolish.py').write_text(
        """
def provide(context):
    return {}
""",
    )

    # Create a config in the repo root (tmp_path) that points to our provider
    cfg = tmp_path / 'repolish.yaml'
    config = {
        'directories': [str(provider)],
        'context': {},
        # post_process will run a small python command to overwrite the
        # generated file with 'FIXED' content. Use the current Python executable
        # as an argv-list to avoid cross-platform tokenization issues.
        # keep as a single string so it validates as a YAML string in the
        # configuration; runtime tokenization is platform-aware in utils.
        'post_process': [
            f"{sys.executable} -c \"open('file.txt','w').write('FIXED')\"",
        ],
        'anchors': {},
        'delete_files': [],
    }
    cfg.write_text(json.dumps(config))

    # Run the CLI to apply changes (not check mode) with cwd set to tmp_path.
    # Monkeypatch CWD by running from within tmp_path using monkeypatch.chdir
    monkeypatch.chdir(tmp_path)

    rv = run(['--config', str(cfg)])
    assert rv == 0, 'CLI should exit 0 on successful apply'

    # The post_process should have replaced file.txt content with 'FIXED'
    final = (tmp_path / 'file.txt').read_text()
    assert final == 'FIXED'
