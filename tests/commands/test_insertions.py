from pathlib import Path

from repolish.commands.apply.insertions import check_registered_insertions
from repolish.providers import SessionBundle


def _write_marker_file(path: Path, body: str) -> None:
    path.write_text(
        f'Header\n<!-- repolish:on:one render -->\n{body}\n<!-- repolish:off:one -->\n',
        encoding='utf-8',
    )


def test_check_registered_insertions_without_staged_output_uses_rendered_diff(
    tmp_path: Path,
) -> None:
    target = tmp_path / 'README.md'
    _write_marker_file(target, '')

    providers = SessionBundle(
        file_insertions={
            'README.md': {
                'render': lambda: 'generated',
            },
        },
        paused_files=set(),
    )

    diffs = check_registered_insertions(providers, tmp_path)

    assert len(diffs) == 1
    path, diff_text = diffs[0]
    assert path == 'README.md'
    assert 'generated' in diff_text


def test_check_registered_insertions_missing_staged_file_falls_back_and_detects_no_drift(
    tmp_path: Path,
) -> None:
    target = tmp_path / 'README.md'
    _write_marker_file(target, 'generated')

    providers = SessionBundle(
        file_insertions={
            'README.md': {
                'render': lambda: 'generated',
            },
        },
        paused_files=set(),
    )

    setup_output = tmp_path / '.staging'
    (setup_output / 'repolish').mkdir(parents=True, exist_ok=True)

    diffs = check_registered_insertions(
        providers,
        tmp_path,
        setup_output=setup_output,
    )

    assert diffs == []
