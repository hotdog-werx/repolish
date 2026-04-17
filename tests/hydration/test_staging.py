"""Tests for hydration staging functionality."""

import textwrap
from pathlib import Path
from typing import cast

from repolish.builder import create_cookiecutter_template
from repolish.config import RepolishConfig
from repolish.hydration.staging import prepare_staging, preprocess_templates
from repolish.loader import Providers


def write_file(p: Path, content: str) -> None:
    """Helper to write a file with proper encoding."""
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding='utf-8')


def make_template_with_unreadable(base: Path, name: str) -> None:
    """Create a template with an unreadable file for testing."""
    tpl_dir = base / name
    repo_dir = tpl_dir / 'repolish'
    repo_dir.mkdir(parents=True, exist_ok=True)
    p = repo_dir / 'secret.txt'
    write_file(p, 'top secret')
    rep = tpl_dir / 'repolish.py'
    rep.write_text(
        textwrap.dedent("""\
    def create_context():
        return {'repo': {'name': 'test_repo'}}
    """),
    )


def test_unreadable_template_file_skipped(tmp_path: Path) -> None:
    """Test that unreadable template files are skipped during preprocessing."""
    # Create a template with a readable secret file
    templates = tmp_path / 'templates'
    make_template_with_unreadable(templates, 'template_a')
    t1 = templates / 'template_a'

    # Stage the template into setup_input using the builder helper
    staging = tmp_path / '.repolish'
    setup_input = staging / 'setup-input'
    _, _ = create_cookiecutter_template(setup_input, [t1])

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


def test_preprocess_templates_preserves_executable_bit(tmp_path: Path) -> None:
    """The executable bit on a staged script is preserved after anchor preprocessing."""
    tpl = tmp_path / 'tpl'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    script = tpl / 'repolish' / 'run.sh'
    script.write_text(
        '#!/bin/bash\n## repolish-start[body]\necho default\nrepolish-end[body]\n',
        encoding='utf-8',
    )

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, _setup_output = prepare_staging(config)
    create_cookiecutter_template(setup_input, [tpl])

    # Local project file has different anchor content — triggers the write_text branch
    base_dir.mkdir(parents=True, exist_ok=True)
    (base_dir / 'run.sh').write_text(
        '#!/bin/bash\n## repolish-start[body]\necho custom\nrepolish-end[body]\n',
        encoding='utf-8',
    )

    # Mark the staged copy executable (mirrors what a provider ships)
    staged = setup_input / '{{cookiecutter._repolish_project}}' / 'run.sh'
    staged.chmod(0o755)

    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        delete_history={},
    )
    preprocess_templates(setup_input, providers, config, base_dir)

    assert staged.stat().st_mode & 0o111, 'executable bit must be preserved after anchor preprocessing'
