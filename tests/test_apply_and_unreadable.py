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
    repo_dir = tpl_dir / 'repolish'
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
        # Use a POSIX-style nested path to ensure path normalization works
        # across platforms (e.g. path/to/file.txt -> path\to\file.txt on Windows)
        return ['path/to/file.txt', 'temp']
    """),
    )


def make_template_with_unreadable(base: Path, name: str) -> None:
    tpl_dir = base / name
    repo_dir = tpl_dir / 'repolish'
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

    # create project with nested file that should be deleted
    project = tmp_path / 'test_repo'
    project.mkdir(parents=True, exist_ok=True)
    nested = project / 'path' / 'to'
    nested.mkdir(parents=True, exist_ok=True)
    (nested / 'file.txt').write_text('to be deleted')

    # create a temp directory inside the project (next to the config) with a
    # trash file that should be deleted by the provider's delete_files entry
    temp_dir = project / 'temp'
    temp_dir.mkdir(parents=True, exist_ok=True)
    (temp_dir / 'trash.txt').write_text('garbage')

    cfg = project / 'repolish.yaml'
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

    monkeypatch.chdir(project)
    rv = run(['--config', str(cfg)])
    assert rv == 0

    # logo should be copied into the project
    logo = project / 'logo.png'
    assert logo.exists()
    assert logo.read_bytes().startswith(b'\x89PNG')

    # deletion should have removed the nested file under the project
    assert not (project / 'path' / 'to' / 'file.txt').exists()
    # and the temp directory under the project should have been removed
    assert not (project / 'temp').exists()


def test_cli_binary_file_check_mode(
    tmp_path: Path,
    monkeypatch: 'pytest.MonkeyPatch',
) -> None:
    """Test that binary files work correctly in CLI check mode."""
    templates = tmp_path / 'templates'
    t1 = templates / 'template_a'
    make_template_with_binary(templates, 'template_a')

    # create project with existing binary file that should be compared
    project = tmp_path / 'test_repo'
    project.mkdir(parents=True, exist_ok=True)

    # Create an existing binary file in the project
    existing_logo = project / 'logo.png'
    existing_logo.write_bytes(
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x02',
    )

    cfg = project / 'repolish.yaml'
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

    # Run check mode - should detect the difference in binary files
    monkeypatch.chdir(project)
    rv = run(['--check', '--config', str(cfg)])

    # Should return 2 (has diffs)
    assert rv == 2


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
    staged_secret = setup_input / '{{cookiecutter._repolish_project}}' / 'secret.txt'
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
