import os
import subprocess
import sys
from pathlib import Path

import pytest
from hotlog import configure_logging, resolve_verbosity
from pytest_mock import MockerFixture

from repolish import utils
from repolish.postprocess import runner


def test_normalize_list_and_string():
    assert runner._normalize_command(['ruff', '--fix', '.']) == (
        'ruff',
        '--fix',
        '.',
    )
    # tokenizes quoted string
    cmd = 'python -c "print(\'x\')"'
    parts = runner._normalize_command(cmd)
    assert parts[0] == 'python' or parts[0] == sys.executable.split('/')[-1]


def test_normalize_empty_and_invalid():
    assert runner._normalize_command('   ') == ()
    with pytest.raises(TypeError):
        runner._normalize_command(123)


def test_normalize_strips_windows_retained_quotes(
    monkeypatch: pytest.MonkeyPatch,
):
    """posix=False (Windows) keeps quote characters inside the tokens.

    Without stripping, `python -c "code"` receives `"code"` as its
    argument: a string-literal expression that runs as a silent no-op.
    Backslashes (Windows paths) must survive, and unquoted tokens stay
    untouched.
    """
    monkeypatch.setattr(runner.os, 'name', 'nt')
    assert runner._normalize_command('python -c "print(1)"') == (
        'python',
        '-c',
        'print(1)',
    )
    assert runner._normalize_command(r'C:\tool --flag "a b"') == (
        r'C:\tool',
        '--flag',
        'a b',
    )


def test_run_records_ok_outcome_with_captured_output(tmp_path: Path):
    """A passing command is recorded as ok with its captured output."""
    configure_logging(verbosity=resolve_verbosity(verbose=0))
    run = utils.run_post_process(
        [[sys.executable, '-c', 'print("hello")']],
        tmp_path,
        tmp_path,
    )
    assert not run.failed
    assert len(run.outcomes) == 1
    outcome = run.outcomes[0]
    assert outcome.status == 'ok'
    assert outcome.returncode == 0
    assert outcome.output == 'hello\n'
    assert outcome.duration_ms >= 0


def test_run_records_failed_outcome_instead_of_raising(tmp_path: Path):
    """A non-zero exit is recorded, not raised; output lands in the outcome."""
    configure_logging(verbosity=resolve_verbosity(verbose=0))
    run = utils.run_post_process(
        [[sys.executable, '-c', 'print("boom"); import sys; sys.exit(7)']],
        tmp_path,
        tmp_path,
    )
    assert run.failed
    outcome = run.outcomes[0]
    assert outcome.status == 'failed'
    assert outcome.returncode == 7
    assert 'boom' in outcome.output


def test_run_stops_at_first_failure_and_records_not_run(tmp_path: Path):
    """Stop-on-first-failure: later commands are recorded but never started."""
    configure_logging(verbosity=resolve_verbosity(verbose=0))
    target = tmp_path / 'later.txt'
    cmds = [
        [sys.executable, '-c', 'import sys; sys.exit(1)'],
        [sys.executable, '-c', f"open('{target.as_posix()}', 'w').write('x')"],
    ]
    run = utils.run_post_process(cmds, tmp_path, tmp_path)
    assert run.failed
    assert [o.status for o in run.outcomes] == ['failed', 'not_run']
    assert not target.exists()


def test_run_records_missing_executable_as_failed(tmp_path: Path):
    """A missing executable is a failed outcome, not a crash."""
    configure_logging(verbosity=resolve_verbosity(verbose=0))
    run = utils.run_post_process(
        [['no-such-binary-xyz', '--flag']],
        tmp_path,
        tmp_path,
    )
    assert run.failed
    outcome = run.outcomes[0]
    assert outcome.status == 'failed'
    assert outcome.returncode is None
    assert outcome.error is not None
    # The recorded error names the binary even where the OS message does
    # not (Windows' WinError 2 names no file).
    assert outcome.error.startswith('no-such-binary-xyz: ')
    assert 'no-such-binary-xyz' in outcome.error


def test_run_captures_output_at_default_verbosity(
    tmp_path: Path,
    mocker: MockerFixture,
):
    """By default (verbosity 0) subprocess stdout is captured (not inherited)."""
    configure_logging(verbosity=resolve_verbosity(verbose=0))
    mock_run = mocker.patch('repolish.postprocess.runner.subprocess.run')
    mock_run.return_value = mocker.Mock(returncode=0, stdout=b'')
    utils.run_post_process([[sys.executable, '-c', 'pass']], tmp_path, tmp_path)
    _, kwargs = mock_run.call_args
    assert kwargs['stdout'] == subprocess.PIPE
    assert kwargs['stderr'] == subprocess.STDOUT


def test_run_normalizes_crlf_in_captured_output(
    tmp_path: Path,
    mocker: MockerFixture,
):
    """Children on Windows write CRLF line endings; recorded output is LF."""
    configure_logging(verbosity=resolve_verbosity(verbose=0))
    mock_run = mocker.patch('repolish.postprocess.runner.subprocess.run')
    mock_run.return_value = mocker.Mock(returncode=0, stdout=b'hello\r\n')
    run = utils.run_post_process(
        [[sys.executable, '-c', 'pass']],
        tmp_path,
        tmp_path,
    )
    assert run.outcomes[0].output == 'hello\n'


def test_run_streams_output_when_verbose(
    tmp_path: Path,
    mocker: MockerFixture,
):
    """With verbosity >= 1 subprocess stdout is inherited (stdout=None)."""
    configure_logging(verbosity=resolve_verbosity(verbose=1))
    try:
        mock_run = mocker.patch('repolish.postprocess.runner.subprocess.run')
        mock_run.return_value = mocker.Mock(returncode=0, stdout=None)
        run = utils.run_post_process(
            [[sys.executable, '-c', 'print("verbose output")']],
            tmp_path,
            tmp_path,
        )
        _, kwargs = mock_run.call_args
        assert kwargs['stdout'] is None
        assert kwargs['stderr'] is None
        assert run.outcomes[0].output == ''
    finally:
        configure_logging(verbosity=resolve_verbosity(verbose=0))


def test_run_post_process_ci_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Commands run and take effect with CI set (no interactive spinner path)."""
    monkeypatch.setenv('CI', '1')
    target = tmp_path / 'ci_out.txt'
    cmds = [
        [sys.executable, '-c', f"open('{target.as_posix()}','w').write('ci')"],
    ]
    utils.run_post_process(cmds, tmp_path, tmp_path)
    assert target.read_text() == 'ci'


def test_run_post_process_combination(tmp_path: Path):
    # mix of None, empty, list, and string commands — last command creates a file
    target = tmp_path / 'out.txt'
    cmds = [
        None,
        '   ',
        [sys.executable, '-c', f"open('{target.as_posix()}','w').write('x')"],
        [sys.executable, '-c', f"open('{target.as_posix()}','w').write('y')"],
    ]
    utils.run_post_process(cmds, tmp_path, tmp_path)
    # file should exist and contain 'y' (last writer)
    assert target.read_text() == 'y'


def test_resolve_placeholders_substitutes_known() -> None:
    values = {'render_dir': '/r', 'render_dir_rel': 'r', 'config_dir': '/c'}
    assert runner._resolve_placeholders(
        ['ruff', 'format', '{render_dir}', '--config={config_dir}/ruff.toml'],
        values,
    ) == ('ruff', 'format', '/r', '--config=/c/ruff.toml')


def test_resolve_placeholders_leaves_non_identifier_braces() -> None:
    # awk's field references are not placeholders: no match, left as-is
    values = {'render_dir': '/r', 'config_dir': '/c'}
    assert runner._resolve_placeholders(["awk '{print $1}'"], values) == ("awk '{print $1}'",)


def test_resolve_placeholders_unknown_token_raises() -> None:
    values = {'render_dir': '/r', 'config_dir': '/c'}
    with pytest.raises(ValueError, match='renderdir'):
        runner._resolve_placeholders(['ruff', 'format', '{renderdir}'], values)


def test_run_post_process_substitutes_placeholders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Placeholders: absolute render/config dirs plus a config-relative path."""
    monkeypatch.setenv('CI', '1')
    config_dir = tmp_path / 'project'
    render_dir = config_dir / '.repolish' / '_' / 'render' / 'repolish'
    render_dir.mkdir(parents=True)
    target = tmp_path / 'paths.txt'
    script = (
        'import os, sys; '
        f"open({str(target)!r}, 'w').write('\\n'.join("
        '[sys.argv[1], sys.argv[2], sys.argv[3], '
        "os.environ['REPOLISH_RENDER_DIR'], os.environ['REPOLISH_CONFIG_DIR']]))"
    )
    cmds = [
        [
            sys.executable,
            '-c',
            script,
            '{render_dir}',
            '{render_dir_rel}',
            '{config_dir}/x',
        ],
    ]
    utils.run_post_process(cmds, render_dir, config_dir)
    lines = target.read_text().splitlines()
    # {render_dir} and {config_dir} are absolute; {render_dir_rel} is the
    # render tree relative to the config directory.
    assert Path(lines[0]).is_absolute()
    assert lines[0] == str(render_dir)
    assert not Path(lines[1]).is_absolute()
    assert lines[1] == os.path.relpath(render_dir, config_dir)
    assert Path(lines[2]).is_absolute()
    assert lines[2] == f'{config_dir}/x'
    assert lines[3] == str(render_dir)
    assert lines[4] == str(config_dir)


def test_run_post_process_absolutizes_relative_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """{render_dir}/{config_dir} stay absolute even from relative inputs.

    The absolute-placeholder promise is enforced by the runner itself, not
    left to caller discipline.
    """
    monkeypatch.setenv('CI', '1')
    monkeypatch.chdir(tmp_path)
    render_dir = tmp_path / '.repolish' / '_' / 'render' / 'repolish'
    render_dir.mkdir(parents=True)
    target = tmp_path / 'paths.txt'
    script = f"import sys; open({str(target)!r}, 'w').write('\\n'.join([sys.argv[1], sys.argv[2]]))"
    cmds = [[sys.executable, '-c', script, '{render_dir}', '{render_dir_rel}']]

    utils.run_post_process(
        cmds,
        Path('.repolish/_/render/repolish'),
        Path.cwd(),
    )

    lines = target.read_text().splitlines()
    assert lines[0] == str(render_dir.resolve())
    assert lines[1] == os.path.relpath(render_dir.resolve(), tmp_path.resolve())


def test_run_outcome_records_only_applied_placeholders(tmp_path: Path) -> None:
    """Each recorded outcome carries only the substitutions it referenced."""
    configure_logging(verbosity=resolve_verbosity(verbose=0))
    render_dir = tmp_path / '.repolish' / '_' / 'render' / 'repolish'
    render_dir.mkdir(parents=True)

    run = utils.run_post_process(
        [[sys.executable, '-c', 'pass', '{render_dir}']],
        render_dir,
        tmp_path,
    )
    assert run.outcomes[0].placeholders == {
        'render_dir': str(render_dir.resolve()),
    }

    # A run that references no placeholder records no substitution fields.
    run = utils.run_post_process(
        [[sys.executable, '-c', 'pass']],
        render_dir,
        tmp_path,
    )
    assert run.outcomes[0].placeholders == {}


def test_run_post_process_unknown_placeholder_fails_before_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown placeholder aborts the run before any command starts."""
    monkeypatch.setenv('CI', '1')
    target = tmp_path / 'out.txt'
    cmds = [
        [sys.executable, '-c', f"open('{target.as_posix()}','w').write('x')"],
        ['ruff', 'format', '{renderdir}'],
    ]
    with pytest.raises(ValueError, match='renderdir'):
        utils.run_post_process(cmds, tmp_path, tmp_path)
    assert not target.exists()


def test_run_post_process_env_var_runs_from_config_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REPOLISH_NO_POST_PROCESS_CD executes commands from the config directory.

    A wrapper (poe, mise) that locates its own config via cwd cannot run from
    inside the render tree — with the env var set the command runs from the
    config dir while {render_dir} still names the rendered tree, so the
    script gets both: a workable cwd and the files' location.
    """
    monkeypatch.setenv('CI', '1')
    monkeypatch.setenv('REPOLISH_NO_POST_PROCESS_CD', '1')
    render_dir = tmp_path / '.repolish' / '_' / 'render' / 'repolish'
    render_dir.mkdir(parents=True)
    config_dir = tmp_path / 'project'
    config_dir.mkdir(parents=True)
    target = tmp_path / 'paths.txt'
    script = (
        'import os, sys; '
        f"open({str(target)!r}, 'w').write('\\n'.join("
        "[sys.argv[1], os.getcwd(), os.environ['REPOLISH_RENDER_DIR']]))"
    )
    cmds = [[sys.executable, '-c', script, '{render_dir}']]
    utils.run_post_process(cmds, render_dir, config_dir)
    lines = target.read_text().splitlines()
    assert lines[0] == str(render_dir)
    assert lines[1] == str(config_dir)
    assert lines[2] == str(render_dir)
