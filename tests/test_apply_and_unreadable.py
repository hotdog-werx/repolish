import json
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, cast

from repolish.builder import create_cookiecutter_template
from repolish.cli import run
from repolish.cookiecutter import preprocess_templates
from repolish.loader import Providers

if TYPE_CHECKING:
    import pytest

    from repolish.config import RepolishConfig


def write_file(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding='utf-8')


def make_template_with_binary(base: Path, name: str) -> None:
    tpl_dir = base / name
    repo_dir = tpl_dir / '{{cookiecutter.repo_name}}'
    repo_dir.mkdir(parents=True, exist_ok=True)
    write_file(
        repo_dir / 'file_a.md',
        textwrap.dedent("""\
    ## repolish-start[readme]
    Default readme
    repolish-end[readme]
    """),
    )
    write_file(repo_dir / 'file_b.toml', 'key = "value"\n')
    # binary logo
    (repo_dir / 'logo.png').write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00\x00')
    # provider
    rep = tpl_dir / 'repolish.py'
    rep.write_text(
        textwrap.dedent("""\
    def create_context():
        return {'repo_name': 'test_repo'}

    def create_delete_files():
        return ['test_repo/file_c', 'temp']
    """),
    )


def make_template_with_unreadable(base: Path, name: str) -> None:
    tpl_dir = base / name
    repo_dir = tpl_dir / '{{cookiecutter.repo_name}}'
    repo_dir.mkdir(parents=True, exist_ok=True)
    p = repo_dir / 'secret.txt'
    write_file(p, 'top secret')
    rep = tpl_dir / 'repolish.py'
    rep.write_text(
        textwrap.dedent("""\
    def create_context():
        return {'repo_name': 'test_repo'}
    """),
    )


def test_apply_flow_with_binary_and_deletion(
    tmp_path: Path,
    monkeypatch: 'pytest.MonkeyPatch',
) -> None:
    templates = tmp_path / 'templates'
    t1 = templates / 'template_a'
    make_template_with_binary(templates, 'template_a')

    # create project with file_c that should be deleted
    project = tmp_path / 'test_repo'
    project.mkdir(parents=True, exist_ok=True)
    (project / 'file_c').write_text('to be deleted')

    # create a temp directory next to the config with a trash file that should be deleted
    temp_dir = tmp_path / 'temp'
    temp_dir.mkdir(parents=True, exist_ok=True)
    (temp_dir / 'trash.txt').write_text('garbage')

    cfg = tmp_path / 'repolish.yaml'
    cfg.write_text(
        json.dumps(
            {
                'directories': [str(t1.as_posix())],
                'context': {},
                'anchors': {},
                'delete_files': [],
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    rv = run(['--config', str(cfg)])
    assert rv == 0

    # logo should be copied into the project
    logo = tmp_path / 'test_repo' / 'logo.png'
    assert logo.exists()
    assert logo.read_bytes().startswith(b'\x89PNG')

    # deletion should have removed file_c
    assert not (tmp_path / 'test_repo' / 'file_c').exists()
    # and the temp directory should have been removed
    assert not (tmp_path / 'temp').exists()


def test_unreadable_template_file_skipped(tmp_path: Path) -> None:
    # Create a template with a readable secret file
    templates = tmp_path / 'templates'
    make_template_with_unreadable(templates, 'template_a')
    t1 = templates / 'template_a'

    # Stage the template into setup_input using the builder helper
    staging = tmp_path / '.repolish'
    setup_input = staging / 'setup-input'
    create_cookiecutter_template(setup_input, [t1])

    # Find the staged secret file and make it unreadable
    staged_secret = setup_input / '{{cookiecutter.repo_name}}' / 'secret.txt'
    assert staged_secret.exists()
    staged_secret.chmod(0)

    # Prepare a minimal providers and config-like object for preprocessing
    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        delete_history={},
    )

    class Cfg:
        def __init__(self) -> None:
            self.anchors: dict[str, str] = {}

    # Call preprocess_templates directly; it should skip the unreadable file and not raise
    preprocess_templates(
        setup_input,
        providers,
        cast('RepolishConfig', Cfg()),
        tmp_path,
    )
