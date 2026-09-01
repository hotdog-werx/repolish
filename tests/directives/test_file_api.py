"""Tests for the file-level preprocessing API (:mod:`repolish.directives.files`).

These exercise the node interface directly — no Jinja rendering, no pipeline —
which is exactly what makes the after-render phase testable in isolation.
"""

import sys
from pathlib import Path
from textwrap import dedent

from repolish.directives import (
    DirectivePhase,
    FilePair,
    process_file,
    run_phase,
    write_if_changed,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text), encoding='utf-8')
    return path


# Mirrors tests/integration/test_directives_after_render.py:
# loop-generated keep blocks reconciled against developer edits — but here the
# "rendered" output is supplied directly, so no full repolish flow is needed.
RENDERED_WITH_LOOP_BLOCKS = """\
## repolish-keep-block[user-note|after-render]: start="<!-- note-start -->" end="<!-- note-end -->"
- alpha
<!-- note-start -->
default alpha note
<!-- note-end -->
- beta
<!-- note-start -->
default beta note
<!-- note-end -->
"""

LOCAL_WITH_CUSTOM_NOTES = """\
- alpha
<!-- note-start -->
custom alpha note
<!-- note-end -->
- beta
<!-- note-start -->
custom beta note
<!-- note-end -->
"""


def test_preprocess_file_after_render_reconciles_repeated_blocks(
    tmp_path: Path,
) -> None:
    template = _write(
        tmp_path / 'render' / 'NOTES.md',
        RENDERED_WITH_LOOP_BLOCKS,
    )
    local = _write(tmp_path / 'base' / 'NOTES.md', LOCAL_WITH_CUSTOM_NOTES)

    result = process_file(template, local, phase=DirectivePhase.AFTER_RENDER)

    assert result is not None
    assert result.changed
    assert 'repolish-keep-block' not in result.content
    assert 'custom alpha note' in result.content
    assert 'custom beta note' in result.content
    assert 'default alpha note' not in result.content
    # process_file is read-only: persisting is the caller's choice
    assert template.read_text(encoding='utf-8') == dedent(
        RENDERED_WITH_LOOP_BLOCKS,
    )


def test_preprocess_file_after_render_keeps_defaults_without_local(
    tmp_path: Path,
) -> None:
    template = _write(
        tmp_path / 'render' / 'NOTES.md',
        RENDERED_WITH_LOOP_BLOCKS,
    )

    # local_path may be None entirely, or point at a missing file
    for local_path in (None, tmp_path / 'base' / 'NOTES.md'):
        result = process_file(
            template,
            local_path,
            phase=DirectivePhase.AFTER_RENDER,
        )
        assert result is not None
        assert result.changed  # directive line stripped
        assert 'repolish-keep-block' not in result.content
        assert 'default alpha note' in result.content


def test_preprocess_file_pre_render_applies_regex_directive(
    tmp_path: Path,
) -> None:
    template = _write(
        tmp_path / 'config.toml',
        """\
        ## repolish-regex[version]: ^version:\\s*(.+)$
        version: 0.0.0
        """,
    )
    local = _write(tmp_path / 'local.toml', 'version: 2.1.0\n')

    result = process_file(template, local)

    assert result is not None
    assert result.changed
    assert 'repolish-regex' not in result.content
    assert '2.1.0' in result.content


def test_preprocess_file_unreadable_template_returns_none(
    tmp_path: Path,
) -> None:
    binary = tmp_path / 'render' / 'blob.bin'
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b'\xff\xfe\x00binary')

    assert process_file(binary, phase=DirectivePhase.AFTER_RENDER) is None


def test_write_if_changed_writes_only_changed_and_preserves_mode(
    tmp_path: Path,
) -> None:
    target = tmp_path / 'x.md'
    target.write_text('old\n', encoding='utf-8')
    target.chmod(0o640)

    template = _write(
        tmp_path / 'tpl.md',
        '## repolish-regex[v]: ^v: (.+)$\nv: 0\n',
    )
    local = _write(tmp_path / 'local.md', 'v: 9\n')
    changed_result = process_file(template, local)
    assert changed_result is not None
    assert changed_result.changed

    assert write_if_changed(target, changed_result)
    assert target.read_text(encoding='utf-8') == changed_result.content
    if sys.platform != 'win32':
        # Windows has no Unix permission bits — chmod only honors read-only.
        assert (target.stat().st_mode & 0o777) == 0o640

    before = target.read_text(encoding='utf-8')
    unchanged_result = process_file(target, local)
    assert unchanged_result is not None
    assert not unchanged_result.changed
    assert not write_if_changed(target, unchanged_result)
    assert target.read_text(encoding='utf-8') == before


def test_run_phase_writes_back_and_reports(tmp_path: Path) -> None:
    render_root = tmp_path / 'render'
    base = tmp_path / 'base'
    changed_file = _write(render_root / 'NOTES.md', RENDERED_WITH_LOOP_BLOCKS)
    unchanged_file = _write(render_root / 'plain.txt', 'nothing to do\n')
    binary_file = render_root / 'blob.bin'
    binary_file.write_bytes(b'\xff\xfe\x00')
    _write(base / 'NOTES.md', LOCAL_WITH_CUSTOM_NOTES)

    result = run_phase(
        DirectivePhase.AFTER_RENDER,
        [
            FilePair(changed_file, base / 'NOTES.md'),
            FilePair(unchanged_file, base / 'plain.txt'),
            FilePair(binary_file, base / 'blob.bin'),
        ],
        post_passes=[],  # no legacy insertions adoption in unit context
    )

    assert result.changed == (str(changed_file),)
    assert result.skipped == (str(binary_file),)
    assert 'custom alpha note' in changed_file.read_text(encoding='utf-8')
    assert unchanged_file.read_text(encoding='utf-8') == 'nothing to do\n'


def test_run_phase_post_passes_are_applied_in_order(tmp_path: Path) -> None:
    def stamp(
        content: str,
        local_content: str,
        *,
        source_path: str | None = None,
    ) -> str:
        return content + f'\n# stamped via post pass (local had {len(local_content)} chars)\n'

    template = _write(tmp_path / 'render' / 'out.txt', 'body\n')
    local = _write(tmp_path / 'base' / 'out.txt', 'dev\n')

    result = run_phase(
        DirectivePhase.AFTER_RENDER,
        [FilePair(template, local)],
        post_passes=[stamp],
    )

    assert result.changed == (str(template),)
    assert '# stamped via post pass (local had 4 chars)' in template.read_text(
        encoding='utf-8',
    )
