"""Text report tests: outcome blocks, captured output, timings section."""

from pathlib import Path

from hotlog import configure_logging, resolve_verbosity

from repolish.postprocess.models import CommandOutcome, PostProcessRun
from repolish.postprocess.report import render_report, write_post_process_report


def _run(cwd: Path, *outcomes: CommandOutcome) -> PostProcessRun:
    return PostProcessRun(cwd=cwd, outcomes=list(outcomes))


def test_ok_block_shows_raw_and_substituted_argv(tmp_path: Path):
    run = _run(
        tmp_path,
        CommandOutcome(
            raw=('ruff', 'format', '{render_dir}'),
            argv=('ruff', 'format', str(tmp_path / 'render')),
            status='ok',
            duration_ms=1200,
        ),
    )
    text = render_report(run)
    assert 'post-process report' in text
    assert f'working directory: {tmp_path}' in text
    assert '$ ruff format {render_dir}' in text
    assert f'  -> ruff format {tmp_path / "render"}' in text
    assert '  ok (1.2s)' in text


def test_failed_block_shows_exit_and_output(tmp_path: Path):
    run = _run(
        tmp_path,
        CommandOutcome(
            raw=('dprint', 'fmt'),
            argv=('dprint', 'fmt'),
            status='failed',
            returncode=1,
            duration_ms=3400,
            output='error: could not parse x.md\n',
        ),
    )
    text = render_report(run)
    assert '  FAILED exit 1 (3.4s)' in text
    assert '  --- output ---' in text
    assert '  error: could not parse x.md' in text


def test_failed_block_notes_streamed_output_at_verbose(tmp_path: Path):
    """At verbosity >= 1 output streamed live, so the report says so."""
    configure_logging(verbosity=resolve_verbosity(verbose=1))
    try:
        run = _run(
            tmp_path,
            CommandOutcome(
                raw=('dprint', 'fmt'),
                argv=('dprint', 'fmt'),
                status='failed',
                returncode=1,
            ),
        )
        text = render_report(run)
        assert '  FAILED exit 1' in text
        assert '  (output streamed live at -v; nothing captured)' in text
        assert '  --- output ---' not in text
    finally:
        configure_logging(verbosity=resolve_verbosity(verbose=0))


def test_missing_executable_block_shows_error(tmp_path: Path):
    run = _run(
        tmp_path,
        CommandOutcome(
            raw=('no-such-tool',),
            argv=('no-such-tool',),
            status='failed',
            returncode=None,
            error='[Errno 2] No such file or directory',
        ),
    )
    text = render_report(run)
    assert '  FAILED' in text
    assert '  [Errno 2] No such file or directory' in text


def test_not_run_block_notes_previous_failure(tmp_path: Path):
    run = _run(
        tmp_path,
        CommandOutcome(
            raw=('true',),
            argv=('true',),
            status='failed',
            returncode=1,
        ),
        CommandOutcome(raw=('after',), argv=('after',), status='not_run'),
    )
    text = render_report(run)
    assert '  not run (previous command failed)' in text


def test_timings_section_appended(tmp_path: Path):
    run = _run(
        tmp_path,
        CommandOutcome(raw=('true',), argv=('true',), status='ok'),
    )
    text = render_report(run, timings='render 183ms · post-process 1.4s')
    assert '--- timings ---' in text
    assert 'render 183ms · post-process 1.4s' in text


def test_no_timings_section_without_timings(tmp_path: Path):
    run = _run(tmp_path)
    assert '--- timings ---' not in render_report(run)


def test_write_post_process_report_creates_parents(tmp_path: Path):
    run = _run(
        tmp_path,
        CommandOutcome(
            raw=('true',),
            argv=('true',),
            status='ok',
            duration_ms=5,
        ),
    )
    report_path = tmp_path / '.repolish' / '_' / 'post-process.txt'
    result = write_post_process_report(report_path, run)
    assert result == report_path
    assert report_path.exists()
    assert '  ok (5ms)' in report_path.read_text(encoding='utf-8')
