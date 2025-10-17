import json
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

from repolish.cli import run
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
    repo_name_var: str = '{{cookiecutter.repo_name}}',
) -> None:
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


def test_integration_cli(
    tmp_path: Path,
    monkeypatch: 'pytest.MonkeyPatch',
) -> None:
    # create two template dirs under tmp_path/templates
    templates = tmp_path / 'templates'
    t1 = templates / 'template_a'
    t2 = templates / 'template_b'
    make_template(templates, 'template_a')
    make_template(templates, 'template_b')

    # create project dir with a file that should be used as local override
    project = tmp_path / 'test_repo'
    write_file(
        project / 'file_a.md',
        textwrap.dedent("""\
    Local override content
    """),
    )
    write_file(
        project / 'file_c',
        textwrap.dedent("""\
    to be deleted
    """),
    )

    # write a config file pointing to the two templates; paths should be POSIX
    cfg = tmp_path / 'repolish.yaml'
    cfg.write_text(
        json.dumps(
            {
                'directories': [str((t1).as_posix()), str((t2).as_posix())],
                'context': {},
                'anchors': {},
                'delete_files': [],
            },
        ),
        encoding='utf-8',
    )

    # run the CLI in check mode with the config path; run() expects argv-like list
    # change working directory to tmp_path so the CLI compares generated files
    # against the project files we created under tmp_path/test_repo
    monkeypatch.chdir(tmp_path)
    rv = run(['--check', '--config', str(cfg)])
    # run should return 2 when differences are found (we expect diffs)
    assert rv == 2

    # Recompute providers from the config file used by the run
    cfg_obj = load_config(cfg)
    providers = build_final_providers(cfg_obj)

    # setup_output path next to config file
    base_dir = cfg.resolve().parent
    setup_output = base_dir / '.repolish' / 'setup-output'

    diffs = check_generated_output(setup_output, providers)

    # assert deletion reported for test_repo/file_c
    assert any(rel == 'test_repo/file_c' and msg == 'PRESENT_BUT_SHOULD_BE_DELETED' for rel, msg in diffs)

    # check provenance: providers.delete_history should have entries for 'test_repo/file_c'
    hist = providers.delete_history.get('test_repo/file_c')
    assert hist is not None
    assert len(hist) >= 1
    last = hist[-1]
    assert last.action == Action.delete
