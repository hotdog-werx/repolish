import json
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

from repolish.commands.apply import command as run_repolish

if TYPE_CHECKING:
    import pytest


def make_template_with_binary(base: Path, name: str) -> None:
    tpl_dir = base / name
    repo_dir = tpl_dir / 'repolish'
    repo_dir.mkdir(parents=True, exist_ok=True)
    (repo_dir / 'file_a.md').write_text(
        textwrap.dedent("""\
## repolish-start[readme]
Default readme
repolish-end[readme]
"""),
    )
    (repo_dir / 'file_b.toml').write_text('key = "value"\n')
    (repo_dir / 'logo.png').write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00\x00')
    rep = tpl_dir / 'repolish.py'
    rep.write_text(
        textwrap.dedent("""
def create_context():
    return {'repo_name': 'test_repo'}

def create_delete_files():
    return ['path/to/file.txt', 'temp']
"""),
    )


def test_apply_flow_with_binary_and_deletion(
    tmp_path: Path,
    monkeypatch: 'pytest.MonkeyPatch',
) -> None:
    templates = tmp_path / 'templates'
    t1 = templates / 'template_a'
    make_template_with_binary(templates, 'template_a')

    project = tmp_path / 'test_repo'
    project.mkdir(parents=True, exist_ok=True)
    nested = project / 'path' / 'to'
    nested.mkdir(parents=True, exist_ok=True)
    (nested / 'file.txt').write_text('to be deleted')

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
    rv = run_repolish(cfg, check_only=False)
    assert rv == 0

    logo = project / 'logo.png'
    assert logo.exists()
    assert logo.read_bytes().startswith(b'\x89PNG')

    assert not (project / 'path' / 'to' / 'file.txt').exists()
    assert not (project / 'temp').exists()


def test_cli_binary_file_check_mode(
    tmp_path: Path,
    monkeypatch: 'pytest.MonkeyPatch',
) -> None:
    templates = tmp_path / 'templates'
    t1 = templates / 'template_a'
    make_template_with_binary(templates, 'template_a')

    project = tmp_path / 'test_repo'
    project.mkdir(parents=True, exist_ok=True)

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

    monkeypatch.chdir(project)
    rv = run_repolish(cfg, check_only=True)

    assert rv == 2
