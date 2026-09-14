import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest
from hotlog import configure_logging, resolve_verbosity
from pytest_mock import MockerFixture

from repolish import utils


def test_normalize_list_and_string():
    assert utils._normalize_command(['ruff', '--fix', '.']) == (
        'ruff',
        '--fix',
        '.',
    )
    # tokenizes quoted string
    cmd = 'python -c "print(\'x\')"'
    parts = utils._normalize_command(cmd)
    assert parts[0] == 'python' or parts[0] == sys.executable.split('/')[-1]


def test_normalize_empty_and_invalid():
    assert utils._normalize_command('   ') == ()
    with pytest.raises(TypeError):
        utils._normalize_command(123)


def test__run_argv_success(tmp_path: Path):
    # run a command that exits 0
    argv = [sys.executable, '-c', 'import sys; sys.exit(0)']
    utils._run_argv(argv, tmp_path)


def test__run_argv_failure(tmp_path: Path):
    argv = [sys.executable, '-c', 'import sys; sys.exit(5)']
    with pytest.raises(subprocess.CalledProcessError):
        utils._run_argv(argv, tmp_path)


def test__run_argv_output_suppressed_on_success(
    tmp_path: Path,
    mocker: MockerFixture,
):
    """By default (verbosity 0) subprocess stdout is captured (not inherited)."""
    configure_logging(verbosity=resolve_verbosity(verbose=0))
    mock_run = mocker.patch('repolish.utils.subprocess.run')
    mock_run.return_value = mocker.Mock(returncode=0, stdout=None)
    argv = [sys.executable, '-c', 'print("hello")']
    utils._run_argv(argv, tmp_path)
    _, kwargs = mock_run.call_args
    assert kwargs['stdout'] == subprocess.PIPE
    assert kwargs['stderr'] == subprocess.STDOUT


def test__run_argv_output_shown_on_failure(
    tmp_path: Path,
    mocker: MockerFixture,
):
    """On failure the captured output is flushed to stdout regardless of verbosity."""
    configure_logging(verbosity=resolve_verbosity(verbose=0))
    fake_output = b'error details\n'
    mock_run = mocker.patch('repolish.utils.subprocess.run')
    mock_run.return_value = mocker.Mock(returncode=1, stdout=fake_output)
    mock_write = mocker.patch('sys.stdout.buffer.write')
    argv = [
        sys.executable,
        '-c',
        'print("error details"); import sys; sys.exit(1)',
    ]
    with pytest.raises(subprocess.CalledProcessError):
        utils._run_argv(argv, tmp_path)
    mock_write.assert_any_call(fake_output)


def test__run_argv_output_inherited_when_verbose(
    tmp_path: Path,
    mocker: MockerFixture,
):
    """With verbosity >= 1 subprocess stdout is inherited (stdout=None)."""
    configure_logging(verbosity=resolve_verbosity(verbose=1))
    try:
        mock_run = mocker.patch('repolish.utils.subprocess.run')
        mock_run.return_value = mocker.Mock(returncode=0, stdout=None)
        argv = [sys.executable, '-c', 'print("verbose output")']
        utils._run_argv(argv, tmp_path)
        _, kwargs = mock_run.call_args
        assert kwargs['stdout'] is None
        assert kwargs['stderr'] is None
    finally:
        configure_logging(verbosity=resolve_verbosity(verbose=0))


def test_run_post_process_ci_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In CI mode run_post_process logs the label instead of showing a spinner.

    When the ``CI`` environment variable is set, :func:`run_post_process` uses
    a plain ``nullcontext`` (no spinner) and emits a structured log entry so
    the CI log captures what's running without interactive Rich output.
    """
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
    assert utils._resolve_placeholders(
        ['ruff', 'format', '{render_dir}', '--config={config_dir}/ruff.toml'],
        values,
    ) == ('ruff', 'format', '/r', '--config=/c/ruff.toml')


def test_resolve_placeholders_leaves_non_identifier_braces() -> None:
    # awk's field references are not placeholders: no match, left as-is
    values = {'render_dir': '/r', 'config_dir': '/c'}
    assert utils._resolve_placeholders(["awk '{print $1}'"], values) == ("awk '{print $1}'",)


def test_resolve_placeholders_unknown_token_raises() -> None:
    values = {'render_dir': '/r', 'config_dir': '/c'}
    with pytest.raises(ValueError, match='renderdir'):
        utils._resolve_placeholders(['ruff', 'format', '{renderdir}'], values)


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
        "[sys.argv[1], sys.argv[2], sys.argv[3], "
        "os.environ['REPOLISH_RENDER_DIR'], os.environ['REPOLISH_CONFIG_DIR']]))"
    )
    cmds = [
        [sys.executable, '-c', script, '{render_dir}', '{render_dir_rel}', '{config_dir}/x'],
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
    script = (
        'import sys; '
        f"open({str(target)!r}, 'w').write('\\n'.join([sys.argv[1], sys.argv[2]]))"
    )
    cmds = [[sys.executable, '-c', script, '{render_dir}', '{render_dir_rel}']]

    utils.run_post_process(cmds, Path('.repolish/_/render/repolish'), Path('.'))

    lines = target.read_text().splitlines()
    assert lines[0] == str(render_dir.resolve())
    assert lines[1] == os.path.relpath(render_dir.resolve(), tmp_path.resolve())


def test_run_post_process_logs_only_applied_placeholders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each command log carries only the substitutions that shaped it.

    The logger is patched (not pytest's caplog) because hotlog is
    structlog-based and never reaches the handlers caplog listens on.
    """
    monkeypatch.setenv('CI', '1')
    mock_info = mock.MagicMock()
    monkeypatch.setattr(utils.logger, 'info', mock_info)
    render_dir = tmp_path / '.repolish' / '_' / 'render' / 'repolish'
    render_dir.mkdir(parents=True)
    config_dir = tmp_path

    utils.run_post_process(
        [[sys.executable, '-c', 'pass', '{render_dir}']],
        render_dir,
        config_dir,
    )
    command_logs = [
        call.kwargs
        for call in mock_info.call_args_list
        if call.args[0] == 'post_process_command'
    ]
    assert command_logs == [
        {
            'command': [sys.executable, '-c', 'pass', str(render_dir.resolve())],
            'cwd': str(render_dir),
            'render_dir': str(render_dir.resolve()),
        },
    ]

    # A run that references no placeholder logs no substitution fields.
    mock_info.reset_mock()
    utils.run_post_process(
        [[sys.executable, '-c', 'pass']],
        render_dir,
        config_dir,
    )
    command_logs = [
        call.kwargs
        for call in mock_info.call_args_list
        if call.args[0] == 'post_process_command'
    ]
    assert command_logs == [
        {'command': [sys.executable, '-c', 'pass'], 'cwd': str(render_dir)},
    ]


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
