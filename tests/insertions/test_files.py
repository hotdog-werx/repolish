"""Standalone tests for the insertions file node (no full repolish flow)."""

from pathlib import Path

from repolish.insertions import (
    apply_insertions_file,
    render_insertions_file,
)

TEMPLATE = """\
header
<!-- repolish:on:badge badge_fn -->
default badge
<!-- repolish:off:badge -->
footer
"""

REGISTRY = {'badge_fn': lambda: 'BADGE'}


def test_render_insertions_file_reads_and_renders_without_writing(tmp_path: Path) -> None:
    target = tmp_path / 'README.md'
    target.write_text(TEMPLATE, encoding='utf-8')

    outcome = render_insertions_file(target, REGISTRY, file_path='README.md')

    assert outcome is not None
    assert outcome.changed
    assert 'BADGE' in outcome.result.text
    assert 'default badge' not in outcome.result.text
    assert '<!-- repolish:on:badge badge_fn -->' in outcome.result.text
    # render is pure: the file on disk is untouched
    assert target.read_text(encoding='utf-8') == TEMPLATE


def test_apply_insertions_file_persists_only_when_changed(tmp_path: Path) -> None:
    target = tmp_path / 'README.md'
    target.write_text(TEMPLATE, encoding='utf-8')

    outcome = apply_insertions_file(target, REGISTRY, file_path='README.md')
    assert outcome is not None
    assert outcome.changed
    assert 'BADGE' in target.read_text(encoding='utf-8')

    # a second pass renders nothing new and leaves the file alone
    again = apply_insertions_file(target, REGISTRY, file_path='README.md')
    assert again is not None
    assert not again.changed


def test_insertions_file_node_skips_missing_and_binary(tmp_path: Path) -> None:
    assert render_insertions_file(tmp_path / 'absent.md', REGISTRY) is None

    binary = tmp_path / 'blob.bin'
    binary.write_bytes(b'\xff\xfe\x00\x01')
    assert apply_insertions_file(binary, REGISTRY) is None
