"""Tests for hydration staging functionality."""

import textwrap
from pathlib import Path

from repolish.builder import stage_templates
from repolish.hydration.staging import preprocess_templates
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
    setup_input = staging / '_' / 'stage'
    _, _ = stage_templates(setup_input, [t1])

    # Find the staged secret file and make it unreadable
    staged_secret = setup_input / 'repolish' / 'secret.txt'
    assert staged_secret.exists()
    staged_secret.chmod(0)

    # Prepare a minimal providers object for preprocessing
    providers = Providers(
        anchors={},
        delete_files=[],
        delete_history={},
    )

    # Call preprocess_templates directly; it should skip the unreadable file and not raise
    preprocess_templates(
        setup_input,
        providers,
        tmp_path,
    )


def test_preprocess_templates_writes_file_when_anchor_content_changes(
    tmp_path: Path,
) -> None:
    """preprocess_templates rewrites the staged file when anchor content differs.

    Exercises the `tpl.write_text(new_text, ...)` branch (staging.py line 65)
    which is only reached when replace_text returns text different from the
    original template content.
    """
    setup_input = tmp_path / '_' / 'stage'
    tpl_dir = setup_input / 'repolish'
    tpl_dir.mkdir(parents=True)

    # Template file has anchor with default placeholder content
    tpl_file = tpl_dir / 'README.md'
    tpl_file.write_text(
        '## repolish-start[intro]\nDefault content\nrepolish-end[intro]\n',
        encoding='utf-8',
    )

    # Local project file has different content inside the same anchor
    base_dir = tmp_path / 'project'
    base_dir.mkdir()
    (base_dir / 'README.md').write_text(
        '## repolish-start[intro]\nProject-specific content\nrepolish-end[intro]\n',
        encoding='utf-8',
    )

    providers = Providers(
        anchors={},
        delete_files=[],
        delete_history={},
    )

    preprocess_templates(setup_input, providers, base_dir)

    # anchor markers are control syntax stripped from the output; the file
    # should differ from the original staged content
    updated = tpl_file.read_text(encoding='utf-8')
    original = '## repolish-start[intro]\nDefault content\nrepolish-end[intro]\n'
    assert updated != original
    assert 'repolish-start' not in updated
