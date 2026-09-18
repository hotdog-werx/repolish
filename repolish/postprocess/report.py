"""Write the human-readable text report for a post-process run.

The report is the `[details]` target behind the summary tree: one block per
command with the user's raw argv, the substituted argv, the outcome, and the
captured output — everything needed to debug a failure without scrolling
back through the terminal.
"""

from pathlib import Path

from hotlog.config import get_config

from repolish.postprocess.models import CommandOutcome, PostProcessRun


def format_duration(ms: int) -> str:
    """Render a duration in ms as `183ms` or, past a second, `1.2s`."""
    if ms >= 1000:
        return f'{ms / 1000:.1f}s'
    return f'{ms}ms'


def _outcome_lines(outcome: CommandOutcome) -> list[str]:
    lines = [f'$ {" ".join(outcome.raw)}', f'  -> {" ".join(outcome.argv)}']
    if outcome.status == 'ok':
        lines.append(f'  ok ({format_duration(outcome.duration_ms)})')
    elif outcome.status == 'not_run':
        lines.append('  not run (previous command failed)')
    elif outcome.error is not None:
        lines.append(f'  FAILED ({format_duration(outcome.duration_ms)})')
        lines.append(f'  {outcome.error}')
    else:
        exit_note = f'exit {outcome.returncode}' if outcome.returncode is not None else 'no exit code'
        lines.append(
            f'  FAILED {exit_note} ({format_duration(outcome.duration_ms)})',
        )
    if outcome.output:
        lines.append('  --- output ---')
        lines.extend(f'  {line}' for line in outcome.output.splitlines())
    elif outcome.status == 'failed' and get_config().verbosity_level >= 1:
        lines.append('  (output streamed live at -v; nothing captured)')
    return lines


def render_report(run: PostProcessRun, timings: str = '') -> str:
    """Render the report text for *run* with an optional *timings* section."""
    lines = ['post-process report', f'working directory: {run.cwd}', '']
    for outcome in run.outcomes:
        lines.extend(_outcome_lines(outcome))
        lines.append('')
    if timings:
        lines.extend(['--- timings ---', timings, ''])
    return '\n'.join(lines)


def write_post_process_report(
    report_path: Path,
    run: PostProcessRun,
    timings: str = '',
) -> Path:
    """Write the report for *run* to *report_path* (parents created)."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(run, timings), encoding='utf-8')
    return report_path
