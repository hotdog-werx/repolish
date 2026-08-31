"""Tests for :func:`repolish.hydration.rendering.rendered_file_pairs`.

This is the pairing half of the after-render phase, previously locked inside
the apply session and only reachable through a full repolish run.
"""

from pathlib import Path

from repolish.hydration import rendered_file_pairs


def test_rendered_file_pairs_strips_staging_prefix(tmp_path: Path) -> None:
    render_root = tmp_path / 'render' / 'repolish'
    plain = render_root / 'docs' / 'guide.md'
    prefixed = render_root / 'sub' / '_repolish.inner.toml'
    plain.parent.mkdir(parents=True)
    prefixed.parent.mkdir(parents=True)
    plain.write_text('# guide\n', encoding='utf-8')
    prefixed.write_text('a = 1\n', encoding='utf-8')

    base = tmp_path / 'base'

    pairs = rendered_file_pairs(tmp_path / 'render', base)

    by_template = {p.template_path: p.local_path for p in pairs}
    assert by_template[plain] == base / 'docs' / 'guide.md'
    # _repolish. filename prefix is staging-only: the local counterpart is the
    # unprefixed destination path
    assert by_template[prefixed] == base / 'sub' / 'inner.toml'


def test_rendered_file_pairs_skips_directories_and_missing_root(
    tmp_path: Path,
) -> None:
    assert rendered_file_pairs(tmp_path / 'render', tmp_path / 'base') == []

    subdir = tmp_path / 'render' / 'repolish' / 'nested'
    subdir.mkdir(parents=True)
    assert rendered_file_pairs(tmp_path / 'render', tmp_path / 'base') == []
