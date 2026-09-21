"""Run post-process commands and record their outcomes.

The runner records every command's result instead of dumping output and
raising: the summary tree and the text report are the display surface. The
config contract is unchanged — shell-free argv execution, placeholder
substitution up front, stop-on-first-failure, and the
``REPOLISH_NO_POST_PROCESS_CD`` escape hatch.
"""

import os
import re
import shlex
import subprocess
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from hotlog import get_logger
from hotlog.config import get_config

from repolish.postprocess.models import (
    CommandOutcome,
    OutcomeStatus,
    PostProcessRun,
)

logger = get_logger(__name__)

# Placeholder pattern for post_process commands: a braced lowercase identifier.
# The conservative character class leaves argument text such as awk's
# '{print $1}' untouched — a bare braced identifier is either one of
# repolish's documented placeholders or a mistake worth failing on.
_PLACEHOLDER_RE = re.compile(r'\{[a-z][a-z0-9_]*\}')


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
        tokens = shlex.split(raw, posix=posix)
        if not posix:
            # posix=False also keeps quote characters in the tokens, which
            # silently changes meaning (`python -c "code"` would receive
            # `"code"` — a string-literal expression, a no-op). Strip one
            # level of matching surrounding quotes, the way a Windows shell
            # would.
            return tuple(
                token[1:-1] if len(token) >= 2 and token[0] == token[-1] and token[0] in '\'"' else token
                for token in tokens
            )
        return tuple(tokens)
    msg = 'post_process entries must be str or list/tuple of str'
    raise TypeError(msg)


def _applied_placeholders(
    argv: Sequence[str],
    values: Mapping[str, str],
) -> dict[str, str]:
    """Return the ``{placeholder: value}`` entries *argv* references.

    Only names actually used in *argv* are returned, so the report shows the
    substitutions that shaped the command — values a developer never
    referenced are noise.
    """
    names: set[str] = set()
    for token in argv:
        names.update(m[1:-1] for m in _PLACEHOLDER_RE.findall(token))
    return {name: values[name] for name in sorted(names)}


def _resolve_placeholders(
    argv: Sequence[str],
    values: Mapping[str, str],
) -> tuple[str, ...]:
    """Substitute ``{placeholder}`` tokens in argv against *values*.

    Runs after tokenization, so a substituted path containing spaces stays a
    single argv element. Any braced identifier that is not a known placeholder
    raises ``ValueError`` — a typo should fail loudly here rather than
    confusingly inside the command.
    """

    def _sub(match: re.Match[str]) -> str:
        name = match[0][1:-1]
        value = values.get(name)
        if value is None:
            msg = f'unknown post_process placeholder {{{name}}}; supported: {", ".join(sorted(values))}'
            raise ValueError(msg)
        return value

    return tuple(_PLACEHOLDER_RE.sub(_sub, token) for token in argv)


def _runs_from_config_dir() -> bool:
    """Return True when REPOLISH_NO_POST_PROCESS_CD is truthy in env.

    Escape hatch for wrappers (poe, mise tasks) that locate their own config
    through the working directory and cannot run from inside the render tree.
    When set, commands execute from the config directory instead — with
    ``{render_dir}`` still pointing at the rendered tree, so a command like
    ``poe format-python {render_dir}`` keeps working.
    """
    val = os.getenv('REPOLISH_NO_POST_PROCESS_CD', '')
    return str(val).lower() in ('1', 'true', 'yes')


def _run_single(
    argv: Sequence[str],
    cwd: Path,
    env: Mapping[str, str] | None = None,
) -> tuple[OutcomeStatus, int | None, int, str, str | None]:
    """Run one argv command in *cwd* and report how it ended.

    Returns ``(status, returncode, duration_ms, output, error)``. Output
    (stdout + stderr) is captured at normal verbosity; at verbosity >= 1
    (-v) it streams live instead and the recorded output is empty.
    """
    verbose = get_config().verbosity_level >= 1
    start = time.perf_counter()
    try:
        completed = subprocess.run(  # noqa: S603 - tokenized argv, no shell
            argv,
            check=False,
            cwd=str(cwd),
            env=dict(env) if env is not None else None,
            stdout=None if verbose else subprocess.PIPE,
            stderr=None if verbose else subprocess.STDOUT,
        )
    except FileNotFoundError as exc:
        # Windows' WinError 2 text names no binary ("The system cannot find
        # the file specified"); prefix argv[0] so the recorded error is
        # actionable on every platform (POSIX errno text already names it).
        return (
            'failed',
            None,
            int((time.perf_counter() - start) * 1000),
            '',
            f'{argv[0]}: {exc}',
        )
    duration_ms = int((time.perf_counter() - start) * 1000)
    # Children on Windows write CRLF line endings; normalize so recorded
    # output compares clean against expectations on every platform.
    output = '' if verbose else (completed.stdout or b'').decode(errors='replace').replace('\r\n', '\n')
    if completed.returncode == 0:
        return 'ok', 0, duration_ms, output, None
    logger.error(
        'post_process_failed',
        command=list(argv),
        returncode=completed.returncode,
    )
    return 'failed', completed.returncode, duration_ms, output, None


def run_post_process(
    commands: Iterable[object],
    cwd: Path,
    config_dir: Path,
) -> PostProcessRun:
    """Run post-processing commands safely and record their outcomes.

    Supports either:
    - list/tuple of argv parts, e.g. ['ruff', '--fix', '.']
    - simple strings without shell metacharacters (they will be tokenized
      with shlex.split and executed without a shell)

    Commands that include shell metacharacters (pipes, redirects, &&, etc.)
    are rejected. If you need complex shell constructs, wrap them in a
    script and reference that script as an argv list or as a single
    executable.

    Commands may reference three placeholders, substituted before execution:
    - ``{render_dir}`` — absolute path to the rendered tree holding the final
      content before it is copied to the project (normally also the working
      directory)
    - ``{render_dir_rel}`` — the same tree relative to the config directory
    - ``{config_dir}`` — absolute path to the directory containing
      `repolish.yaml`
    The absolute ones are also exported as ``REPOLISH_RENDER_DIR`` /
    ``REPOLISH_CONFIG_DIR`` in the command's environment. Setting
    ``REPOLISH_NO_POST_PROCESS_CD`` executes commands from the config
    directory instead of the render tree (for wrappers that find their config
    via cwd); ``{render_dir}`` keeps pointing at the files either way.

    Args:
        commands: Iterable of command specifications (str or Sequence[str]).
        cwd: Rendered tree to process ({render_dir}); made absolute here.
        config_dir: Directory containing `repolish.yaml` ({config_dir});
            made absolute here.

    Raises:
        ValueError: when a command contains an unknown ``{placeholder}``.
    """
    # Absolutize both paths here so the documented placeholder promise holds
    # for any caller — the config layer already resolves config_dir
    # (config_file.resolve().parent) and staging builds the render tree from
    # it, but the absolute-vs-relative contract is a public promise, not a
    # caller's discipline to maintain.
    render_dir = cwd.resolve()
    config_dir = config_dir.resolve()
    values = {
        'render_dir': str(render_dir),
        'render_dir_rel': os.path.relpath(render_dir, config_dir),
        'config_dir': str(config_dir),
    }
    normalised = [_normalize_command(raw) for raw in commands if raw is not None]
    normalised = [argv for argv in normalised if argv]
    run = PostProcessRun(cwd=render_dir)
    if not normalised:
        return run
    # Resolve every command before starting any of them so an unknown
    # placeholder fails the run up front instead of mid-sequence.
    resolved = [_resolve_placeholders(argv, values) for argv in normalised]
    logger.debug(
        'post_process_start',
        command_count=len(resolved),
        render_dir=str(render_dir),
    )
    env = {
        **os.environ,
        'REPOLISH_RENDER_DIR': values['render_dir'],
        'REPOLISH_CONFIG_DIR': values['config_dir'],
    }
    process_cwd = config_dir if _runs_from_config_dir() else cwd
    for raw_argv, argv in zip(normalised, resolved, strict=True):
        placeholders = _applied_placeholders(raw_argv, values)
        if run.failed:
            run.outcomes.append(
                CommandOutcome(
                    raw=tuple(raw_argv),
                    argv=argv,
                    placeholders=placeholders,
                    status='not_run',
                ),
            )
            continue
        fields: dict[str, object] = {
            'command': list(argv),
            'cwd': str(process_cwd),
        }
        fields.update(placeholders)
        logger.debug('post_process_command', **fields)
        status, returncode, duration_ms, output, error = _run_single(
            argv,
            process_cwd,
            env,
        )
        run.outcomes.append(
            CommandOutcome(
                raw=tuple(raw_argv),
                argv=argv,
                placeholders=placeholders,
                status=status,
                returncode=returncode,
                duration_ms=duration_ms,
                output=output,
                error=error,
            ),
        )
    return run
