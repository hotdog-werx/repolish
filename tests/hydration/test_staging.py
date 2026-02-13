"""Tests for hydration staging functionality."""

import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, cast

from repolish.builder import create_cookiecutter_template
from repolish.hydration.staging import preprocess_templates
from repolish.loader import Providers

if TYPE_CHECKING:
    from repolish.config import RepolishConfig


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
        return {'repo_name': 'test_repo'}
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
