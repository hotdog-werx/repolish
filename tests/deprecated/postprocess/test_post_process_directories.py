import json
from pathlib import Path
from typing import TYPE_CHECKING

from repolish.commands.apply import command as run

if TYPE_CHECKING:
    import pytest


def test_post_process_applies_and_fixes_file(
    tmp_path: Path,
    monkeypatch: 'pytest.MonkeyPatch',
):
    provider = tmp_path / 'provider'
    provider.mkdir()
    (provider / 'repolish').mkdir()
    templated = provider / 'repolish' / 'file.txt'
    templated.write_text('NEEDS_FORMATTING')

    (provider / 'repolish' / 'fix.py').write_text(
        """
open('file.txt','w').write('FIXED')
""",
    )

    (provider / 'repolish.py').write_text(
        """
def provide(context):
    return {}
""",
    )

    cfg = tmp_path / 'repolish.yaml'
    config = {
        'directories': [str(provider)],
        'context': {},
        'post_process': ['python fix.py'],
        'anchors': {},
        'delete_files': [],
    }
    cfg.write_text(json.dumps(config))

    monkeypatch.chdir(tmp_path)

    rv = run(cfg, check_only=False)
    assert rv == 0

    final = (tmp_path / 'file.txt').read_text()
    assert final == 'FIXED'
