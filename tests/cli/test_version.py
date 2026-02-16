import sys
from typing import TYPE_CHECKING

import pytest

from repolish.cli.main import app
from repolish.version import __version__

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch


def test_main_version_prints_and_exits(
    monkeypatch: 'MonkeyPatch',
    capsys: 'CaptureFixture[str]',
) -> None:
    # Simulate calling the program with --version
    monkeypatch.setattr(sys, 'argv', ['repolish', '--version'])
    with pytest.raises(SystemExit) as exc:
        app()
    # argparse uses exit code 0 for --version
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert __version__ in captured.out
