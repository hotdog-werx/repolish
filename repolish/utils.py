import os
import shlex
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import IO

from hotlog import get_logger
from hotlog.config import get_config
from hotlog.live import LiveLogger, live_logging

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


def _run_argv(
    argv: Sequence[str],
    cwd: Path,
    *,
    live: LiveLogger | None = None,
) -> None:
    """Run an argv command in cwd, raise CalledProcessError on non-zero exit.

    Output (stdout + stderr) is captured and only printed when the current
    verbosity level is >= 1 (-v) or the command exits non-zero.
    """
    if live is not None:
        live.info('post_process_command', command=list(argv), cwd=str(cwd))
    else:
        logger.info('post_process_command', command=argv, cwd=str(cwd))
    # Run the tokenized argv without a shell. This avoids shell=True based
    # injection risk while keeping behavior simple and convenient for
    # developers. If you need complex shell pipelines, commit a script and
    # call it from `post_process`.
    # We intentionally run an argv list (not shell=True) and
    # accept that development tooling runs commands from repositories.
    verbose = get_config().verbosity_level >= 1
    completed = subprocess.run(  # noqa: S603 - see above
        argv,
        check=False,
        cwd=str(cwd),
        stdout=None if verbose else subprocess.PIPE,
        stderr=None if verbose else subprocess.STDOUT,
    )
    if completed.returncode != 0:
        if not verbose and completed.stdout:
            sys.stdout.buffer.write(completed.stdout)
            sys.stdout.flush()
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
    normalised = [_normalize_command(raw) for raw in commands if raw is not None]
    normalised = [argv for argv in normalised if argv]
    if not normalised:
        return
    label = f'post-process ({len(normalised)} command{"s" if len(normalised) != 1 else ""})'
    with live_logging(label) as live:
        for argv in normalised:
            _run_argv(argv, cwd, live=live)


def ensure_dot_repolish(base_dir: Path) -> Path:
    """Create the .repolish directory under base_dir and write a catch-all .gitignore if absent.

    Returns the .repolish Path.
    """
    repolish_dir = base_dir / '.repolish'
    repolish_dir.mkdir(parents=True, exist_ok=True)
    gitignore = repolish_dir / '.gitignore'
    if not gitignore.exists():
        gitignore.write_text('*\n', encoding='utf-8')
    return repolish_dir


def read_text_utf8(path: Path) -> str:
    """Read text from a file using UTF-8 encoding."""
    return path.read_text(encoding='utf-8')


def write_text_utf8(path: Path, content: str) -> None:
    """Write text to a file using UTF-8 encoding."""
    path.write_text(content, encoding='utf-8')


def open_utf8(path: Path, mode: str = 'r') -> IO[str]:
    """Open a file with UTF-8 encoding."""
    return path.open(mode, encoding='utf-8')
