"""Tests for the shared hydration write helpers."""

import sys
from pathlib import Path

import pytest

from repolish.hydration.misc import write_mode_from


@pytest.mark.skipif(
    sys.platform == 'win32',
    reason='Windows does not support Unix executable bits',
)
def test_write_mode_from_inherits_the_originals_full_mode(tmp_path: Path) -> None:
    """Content lands byte-exact in the original file's permission bits.

    The full mode is inherited, not just the executable bit: a fresh
    destination is created with the original's mode instead of the
    process default, which is what the apply tier's copy propagates
    onward.
    """
    original = tmp_path / 'original.sh'
    original.write_text('#!/bin/bash\n', encoding='utf-8')
    original.chmod(0o755)
    dest = tmp_path / 'rendered' / 'staged.sh'
    dest.parent.mkdir()

    write_mode_from(dest, 'rendered\n', mode_source=original)

    assert dest.read_text(encoding='utf-8') == 'rendered\n'
    assert dest.stat().st_mode == original.stat().st_mode
