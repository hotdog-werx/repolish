import subprocess
import sys
from pathlib import Path

import pytest
from hotlog import configure_logging, resolve_verbosity

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


def test__run_argv_output_suppressed_on_success(tmp_path: Path, mocker):
    """By default (verbosity 0) subprocess stdout is captured (not inherited)."""
    configure_logging(verbosity=resolve_verbosity(verbose=0))
    mock_run = mocker.patch('repolish.utils.subprocess.run')
    mock_run.return_value = mocker.Mock(returncode=0, stdout=None)
    argv = [sys.executable, '-c', 'print("hello")']
    utils._run_argv(argv, tmp_path)
    _, kwargs = mock_run.call_args
    assert kwargs['stdout'] == subprocess.PIPE
    assert kwargs['stderr'] == subprocess.STDOUT


def test__run_argv_output_shown_on_failure(tmp_path: Path, mocker):
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


def test__run_argv_output_inherited_when_verbose(tmp_path: Path, mocker):
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


def test_run_post_process_combination(tmp_path: Path):
    # mix of None, empty, list, and string commands — last command creates a file
    target = tmp_path / 'out.txt'
    cmds = [
        None,
        '   ',
        [sys.executable, '-c', f"open('{target.as_posix()}','w').write('x')"],
        [sys.executable, '-c', f"open('{target.as_posix()}','w').write('y')"],
    ]
    utils.run_post_process(cmds, tmp_path)
    # file should exist and contain 'y' (last writer)
    assert target.read_text() == 'y'
