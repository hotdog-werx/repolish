import json
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

from repolish.commands.apply import command as run_repolish

if TYPE_CHECKING:
    import pytest


def write_file(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding='utf-8')


def make_template(
    base: Path,
    name: str,
    repo_name_var: str = 'repolish',
) -> Path:
    tpl_dir = base / name
    # cookiecutter root contains a directory with the repo name
    repo_dir = tpl_dir / repo_name_var
    (repo_dir).mkdir(parents=True, exist_ok=True)
    # file_a.md with an anchor
    write_file(
        repo_dir / 'file_a.md',
        textwrap.dedent("""\
        ## repolish-start[readme]
        Default readme
        repolish-end[readme]
        """),
    )
    # file_b.toml with a regex placeholder line we will preserve
    write_file(
        repo_dir / 'file_b.toml',
        textwrap.dedent("""\
        key = "value"
        ## repolish-regex[keep]: ^important=.*
        """),
    )
    # repolish.py provider that contributes context and deletion
    repolish_py = tpl_dir / 'repolish.py'
    repolish_py.write_text(
        textwrap.dedent("""\
        def create_context():
            return {'repo_name': 'test_repo'}

        def create_delete_files():
            return ['test_repo/file_c']
        """),
        encoding='utf-8',
    )
    return tpl_dir


# deprecated test moved to tests/deprecated/integration/test_integration_directories.py
# (integration CLI flow using the deprecated `directories` config key)


PRESERVES_CUSTOM_BLOCK_TPL = r"""
name: ci-checks

on: [push]

jobs:
    run-checks:
    runs-on: ubuntu-latest

## repolish-regex[additional-jobs]: ^## post-check-jobs([\s\S]*)$
## post-check-jobs
"""
PRESERVES_CUSTOM_BLOCK_PROJECT = """
name: ci-checks

jobs:
    run-checks:
        runs-on: ubuntu-latest

## post-check-jobs
## Custom job 1
    steps:
        - run: echo "Job 1"
"""


# deprecated test moved to tests/deprecated/integration/test_integration_directories.py
# (preserves-regex integration test that used the deprecated `directories` config key)

# deprecated test moved to tests/deprecated/integration/test_integration_directories.py
# (context-provider merge test exercised via deprecated `directories` config)


def test_integration_emoji_encoding(
    tmp_path: Path,
    monkeypatch: 'pytest.MonkeyPatch',
) -> None:
    """Test that repolish handles emoji content correctly (exposes Windows encoding issues)."""
    # create template dir with emoji content
    templates = tmp_path / 'templates'
    tpl_dir = templates / 'emoji_template'
    repo_dir = tpl_dir / 'repolish'
    repo_dir.mkdir(parents=True, exist_ok=True)

    # file with emoji content
    write_file(
        repo_dir / 'CHANGELOG.md',
        textwrap.dedent("""\
        # Changelog

        ## 🐛 Bug Fixes
        - Fixed something important

        ## 🚀 Features
        - Added something cool
        """),
    )

    # repolish.py provider file (required for template validation)
    repolish_py = tpl_dir / 'repolish.py'
    write_file(
        repolish_py,
        textwrap.dedent("""\
        def create_context():
            return {}

        def create_delete_files():
            return []
        """),
    )

    # write config file
    cfg = tmp_path / 'repolish.yaml'
    cfg.write_text(
        json.dumps(
            {
                'directories': [str((tpl_dir).as_posix())],
                'context': {},
                'anchors': {},
                'delete_files': [],
            },
        ),
        encoding='utf-8',
    )

    # run repolish apply
    monkeypatch.chdir(tmp_path)
    rv = run_repolish(cfg, check_only=False)
    assert rv == 0

    # verify emoji content was preserved (file is copied to current directory)
    result_file = tmp_path / 'CHANGELOG.md'
    assert result_file.exists()
    content = result_file.read_text(encoding='utf-8')
    assert '🐛 Bug Fixes' in content
    assert '🚀 Features' in content


def test_cli_provider_order_with_overrides(
    tmp_path: Path,
    monkeypatch: 'pytest.MonkeyPatch',
) -> None:
    """Provider order and template_overrides should influence staging.

    We create two simple provider templates (p1 and p2) both defining
    ``foo.txt`` with different content.  The configuration pins ``foo.txt``
    to ``p1`` using ``template_overrides`` even though ``p2`` comes later in
    ``providers_order``.  After running the CLI the file copied into the
    working directory should reflect the override.
    """
    # provider 1
    p1 = tmp_path / 'p1'
    (p1 / 'templates' / 'repolish').mkdir(parents=True)
    write_file(p1 / 'templates' / 'repolish' / 'foo.txt', 'from p1')
    write_file(
        p1 / 'templates' / 'repolish.py',
        'def create_context():\n    return {}\n',
    )

    # provider 2
    p2 = tmp_path / 'p2'
    (p2 / 'templates' / 'repolish').mkdir(parents=True)
    write_file(p2 / 'templates' / 'repolish' / 'foo.txt', 'from p2')
    write_file(
        p2 / 'templates' / 'repolish.py',
        'def create_context():\n    return {}\n',
    )

    cfg = tmp_path / 'repolish.yaml'
    cfg.write_text(
        json.dumps(
            {
                'providers_order': ['p1', 'p2'],
                'providers': {
                    'p1': {'directory': './p1'},
                    'p2': {'directory': './p2'},
                },
                'template_overrides': {'foo.txt': 'p1'},
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    rv = run_repolish(cfg, check_only=False)
    assert rv == 0

    # p1 override should take effect even though p2 is last
    assert (tmp_path / 'foo.txt').read_text() == 'from p1'
