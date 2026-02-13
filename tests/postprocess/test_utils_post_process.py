import subprocess
import sys
from pathlib import Path

import pytest

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
