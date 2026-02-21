import json
import textwrap
from pathlib import Path
from pathlib import Path as _Path
from typing import TYPE_CHECKING

from repolish.commands.apply import command as run_repolish
from repolish.config import load_config
from repolish.cookiecutter import build_final_providers, check_generated_output
from repolish.loader import Action

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
    repo_dir = tpl_dir / repo_name_var
    (repo_dir).mkdir(parents=True, exist_ok=True)
    write_file(
        repo_dir / 'file_a.md',
        textwrap.dedent("""\
## repolish-start[readme]
Default readme
repolish-end[readme]
"""),
    )
    write_file(
        repo_dir / 'file_b.toml',
        textwrap.dedent("""\
key = "value"
## repolish-regex[keep]: ^important=.*
"""),
    )
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


def test_integration_cli(
    tmp_path: Path,
    monkeypatch: 'pytest.MonkeyPatch',
) -> None:
    templates = tmp_path / 'templates'
    t1 = templates / 'template_a'
    t2 = templates / 'template_b'
    make_template(templates, 'template_a')
    make_template(templates, 'template_b')

    project = tmp_path / 'test_repo'
    write_file(project / 'file_a.md', 'Local override content')
    write_file(project / 'file_c', 'to be deleted')

    cfg = tmp_path / 'repolish.yaml'
    cfg.write_text(
        json.dumps(
            {
                'directories': [str((t1).as_posix()), str((t2).as_posix())],
                'context': {},
                'context_overrides': {'repo_name': 'overridden_repo_name'},
                'anchors': {},
                'delete_files': [],
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    rv = run_repolish(cfg, check_only=True)
    assert rv == 2

    cfg_obj = load_config(cfg)
    providers = build_final_providers(cfg_obj)

    base_dir = cfg.resolve().parent
    setup_output = base_dir / '.repolish' / 'setup-output'

    diffs = check_generated_output(setup_output, providers, tmp_path)

    assert any(
        _Path(rel).as_posix() == 'test_repo/file_c' and msg == 'PRESENT_BUT_SHOULD_BE_DELETED' for rel, msg in diffs
    )

    hist = providers.delete_history.get('test_repo/file_c')
    assert hist is not None
    assert len(hist) >= 1
    last = hist[-1]
    assert last.action == Action.delete


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


def test_integration_regex_preserves_custom_block(
    tmp_path: Path,
    monkeypatch: 'pytest.MonkeyPatch',
) -> None:
    templates = tmp_path / 'templates'
    tpl = make_template(templates, 'template_regex')

    tpl_repolish = tpl / 'repolish'
    wf_dir = tpl_repolish / '.github' / 'workflows'
    wf_dir.mkdir(parents=True, exist_ok=True)
    ci_template = wf_dir / '_repolish.ci-checks.yaml'
    ci_template.write_text(PRESERVES_CUSTOM_BLOCK_TPL, encoding='utf-8')

    (tpl / 'repolish.py').write_text(
        textwrap.dedent("""\
def create_context():
    return {'repo_name': 'repolish'}

def create_file_mappings():
    return {
        '.github/workflows/ci-checks.yaml': '.github/workflows/_repolish.ci-checks.yaml'
    }
"""),
        encoding='utf-8',
    )

    project = tmp_path
    write_file(
        project / '.github' / 'workflows' / 'ci-checks.yaml',
        PRESERVES_CUSTOM_BLOCK_PROJECT,
    )

    cfg = project / 'repolish.yaml'
    cfg.write_text(
        json.dumps(
            {
                'directories': [str((tpl).as_posix())],
                'context': {},
                'anchors': {},
                'delete_files': [],
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(project)
    rv = run_repolish(cfg, check_only=False)
    assert rv == 0

    dest_file = project / '.github' / 'workflows' / 'ci-checks.yaml'
    result = dest_file.read_text()
    assert '## Custom job 1' in result

    src_copy = project / '.github' / 'workflows' / '_repolish.ci-checks.yaml'
    assert not src_copy.exists()


def test_integration_context_provider_uses_config_and_merges(
    tmp_path: Path,
    monkeypatch: 'pytest.MonkeyPatch',
) -> None:
    templates = tmp_path / 'templates'
    tpl = make_template(templates, 'template_ctx')

    (tpl / 'repolish.py').write_text(
        textwrap.dedent("""\
def create_context(ctx=None):
    incoming = (ctx or {}).get('my_var')
    return {'my_var': 'A', 'my_collection': f"{incoming}b"}
"""),
        encoding='utf-8',
    )

    cfg = tmp_path / 'repolish.yaml'
    cfg.write_text(
        json.dumps(
            {
                'directories': [str((tpl).as_posix())],
                'context': {'my_var': 'a'},
                'anchors': {},
                'delete_files': [],
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    rv = run_repolish(cfg, check_only=False)
    assert rv == 0

    setup_input = (cfg.resolve().parent) / '.repolish' / 'setup-input'
    cookie_path = setup_input / 'cookiecutter.json'
    assert cookie_path.exists()

    data = json.loads(cookie_path.read_text(encoding='utf-8'))

    assert data.get('my_var') == 'a'
    assert data.get('my_collection') == 'ab'


def test_integration_emoji_encoding(
    tmp_path: Path,
    monkeypatch: 'pytest.MonkeyPatch',
) -> None:
    templates = tmp_path / 'templates'
    tpl_dir = templates / 'emoji_template'
    repo_dir = tpl_dir / 'repolish'
    repo_dir.mkdir(parents=True, exist_ok=True)

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

    monkeypatch.chdir(tmp_path)
    rv = run_repolish(cfg, check_only=False)
    assert rv == 0

    result_file = tmp_path / 'CHANGELOG.md'
    assert result_file.exists()
    content = result_file.read_text(encoding='utf-8')
    assert '🐛 Bug Fixes' in content
    assert '🚀 Features' in content
