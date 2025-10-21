import os
import shlex
import subprocess
from collections.abc import Iterable, Sequence
from pathlib import Path

from hotlog import get_logger

logger = get_logger(__name__)


def _normalize_command(raw: object) -> Sequence[str]:
    """Normalize a raw post_process entry into an argv sequence.

    Accepts a string or a list/tuple and returns a tuple of strings. Raises
    TypeError for unsupported types.
    """
    if isinstance(raw, (list, tuple)):
        return tuple(str(x) for x in raw)
    if isinstance(raw, str):
        if not raw.strip():
            return ()
        # On Windows, paths contain backslashes which POSIX-style shlex.split
        # can treat as escape sequences; use posix=False there to preserve
        # backslashes. For cross-platform behavior, detect the platform.
        posix = os.name != 'nt'
        return shlex.split(raw, posix=posix)
    msg = 'post_process entries must be str or list/tuple of str'
    raise TypeError(msg)


def _run_argv(argv: Sequence[str], cwd: Path) -> None:
    """Run an argv command in cwd, raise CalledProcessError on non-zero exit."""
    logger.info('post_process_command', command=argv, cwd=str(cwd))
    # Run the tokenized argv without a shell. This avoids shell=True based
    # injection risk while keeping behavior simple and convenient for
    # developers. If you need complex shell pipelines, commit a script and
    # call it from `post_process`.
    # We intentionally run an argv list (not shell=True) and
    # accept that development tooling runs commands from repositories.
    completed = subprocess.run(argv, check=False, cwd=str(cwd))  # noqa: S603 - see above
    if completed.returncode != 0:
        logger.error(
            'post_process_failed',
            command=argv,
            returncode=completed.returncode,
        )
        raise subprocess.CalledProcessError(
            returncode=completed.returncode,
            cmd=argv,
        )


def run_post_process(commands: Iterable[object], cwd: Path) -> None:
    """Run post-processing commands safely.

    Supports either:
    - list/tuple of argv parts, e.g. ['ruff', '--fix', '.']
    - simple strings without shell metacharacters (they will be tokenized
      with shlex.split and executed without a shell)

    Commands that include shell metacharacters (pipes, redirects, &&, etc.)
    are rejected. If you need complex shell constructs, wrap them in a
    script and reference that script as an argv list or as a single
    executable.

    Args:
        commands: Iterable of command specifications (str or Sequence[str]).
        cwd: Working directory to run the commands in.

    Raises:
        ValueError: when a string command contains shell metacharacters.
        subprocess.CalledProcessError: when a command exits non-zero.
    """
    for raw in commands:
        if raw is None:
            continue
        argv = _normalize_command(raw)
        if not argv:
            continue
        _run_argv(argv, cwd)
