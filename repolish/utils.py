import contextlib
import difflib
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import IO, TypeVar

from hotlog import get_logger
from hotlog.config import get_config
from hotlog.live import live_logging

V = TypeVar('V')

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
        return shlex.split(raw, posix=posix)
    msg = 'post_process entries must be str or list/tuple of str'
    raise TypeError(msg)


def _applied_placeholders(
    argv: Sequence[str],
    values: Mapping[str, str],
) -> dict[str, str]:
    """Return the ``{placeholder: value}`` entries *argv* references.

    Only names actually used in *argv* are returned, so the command log
    shows the substitutions that shaped it — values a developer never
    referenced are noise.
    """
    names: set[str] = set()
    for token in argv:
        names.update(m[1:-1] for m in _PLACEHOLDER_RE.findall(token))
    return {name: values[name] for name in sorted(names)}


def _run_argv(
    argv: Sequence[str],
    cwd: Path,
    env: Mapping[str, str] | None = None,
    placeholders: Mapping[str, str] | None = None,
) -> None:
    """Run an argv command in cwd, raise CalledProcessError on non-zero exit.

    Output (stdout + stderr) is captured and only printed when the current
    verbosity level is >= 1 (-v) or the command exits non-zero.
    """
    fields: dict[str, object] = {'command': list(argv), 'cwd': str(cwd)}
    if placeholders:
        fields.update(placeholders)
    logger.info('post_process_command', **fields)
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
        env=dict(env) if env is not None else None,
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


def _post_process_runs_from_config_dir() -> bool:
    """Return True when REPOLISH_NO_POST_PROCESS_CD is truthy in env.

    Escape hatch for wrappers (poe, mise tasks) that locate their own config
    through the working directory and cannot run from inside the render tree.
    When set, commands execute from the config directory instead — with
    ``{render_dir}`` still pointing at the rendered tree, so a command like
    ``poe format-python {render_dir}`` keeps working.
    """
    val = os.getenv('REPOLISH_NO_POST_PROCESS_CD', '')
    return str(val).lower() in ('1', 'true', 'yes')


def run_post_process(
    commands: Iterable[object],
    cwd: Path,
    config_dir: Path,
) -> None:
    """Run post-processing commands safely.

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
        subprocess.CalledProcessError: when a command exits non-zero.
    """
    # Absolutize both paths here so the documented placeholder promise holds
    # for any caller — the config layer already resolves config_dir
    # (config_file.resolve().parent) and staging builds the render tree from
    # it, but this is a shared utility and the absolute-vs-relative contract
    # is a public promise, not a caller's discipline to maintain.
    render_dir = cwd.resolve()
    config_dir = config_dir.resolve()
    values = {
        'render_dir': str(render_dir),
        'render_dir_rel': os.path.relpath(render_dir, config_dir),
        'config_dir': str(config_dir),
    }
    normalised = [_normalize_command(raw) for raw in commands if raw is not None]
    normalised = [argv for argv in normalised if argv]
    if not normalised:
        return
    # Resolve every command before starting any of them so an unknown
    # placeholder fails the run up front instead of mid-sequence.
    resolved = [_resolve_placeholders(argv, values) for argv in normalised]
    label = f'post-process ({len(resolved)} command{"s" if len(resolved) != 1 else ""})'
    in_ci = os.environ.get('CI', '').strip().lower() in ('1', 'true', 'yes')
    ctx = contextlib.nullcontext() if in_ci else live_logging(label)
    env = {
        **os.environ,
        'REPOLISH_RENDER_DIR': values['render_dir'],
        'REPOLISH_CONFIG_DIR': values['config_dir'],
    }
    process_cwd = config_dir if _post_process_runs_from_config_dir() else cwd
    if in_ci:
        logger.info('post_process', label=label)
    with ctx:
        for raw_argv, argv in zip(normalised, resolved, strict=True):
            _run_argv(argv, process_cwd, env, _applied_placeholders(raw_argv, values))


def ensure_dot_repolish(base_dir: Path) -> Path:
    """Create the .repolish directory under base_dir and write a catch-all .gitignore if absent.

    Returns the .repolish Path.
    """
    repolish_dir = base_dir / '.repolish'
    repolish_dir.mkdir(parents=True, exist_ok=True)
    gitignore = repolish_dir / '.gitignore'
    if not gitignore.exists():
        gitignore.write_text('*\n!_/\n', encoding='utf-8')
    return repolish_dir


def ensure_meta_dir(base_dir: Path) -> Path:
    """Create the .repolish/_/ meta directory and write a catch-all .gitignore if absent.

    Tools that need access to specific paths inside _/ (e.g. dprint reaching
    _/render/) should negate those paths in their own config.  The .gitignore
    here ignores everything so nothing leaks into version control by default.

    Returns the .repolish/_/ Path.
    """
    meta_dir = base_dir / '.repolish' / '_'
    meta_dir.mkdir(parents=True, exist_ok=True)
    gitignore = meta_dir / '.gitignore'
    if not gitignore.exists():
        gitignore.write_text('*\n', encoding='utf-8')
    return meta_dir


def open_utf8(path: Path, mode: str = 'r') -> IO[str]:
    """Open a file with UTF-8 encoding."""
    return path.open(mode, encoding='utf-8')


def path_slug(path: str, sep: str = '--') -> str:
    """Convert a path to a safe filename slug.

    Replaces path separators with a delimiter for use in report filenames,
    debug files, and other contexts where paths need to be embedded in
    filenames.

    Args:
        path: A relative path (e.g., 'some/nested/file.md')
        sep: The separator to use in the slug (default '--')

    Returns:
        A slugified path (e.g., 'some--nested--file.md')
    """
    return path.replace('/', sep).replace('\\', sep)


def build_unified_diff(rel_path: str, current: str, rendered: str) -> str:
    """Build a unified diff between current and rendered text.

    Args:
        rel_path: Path to use in diff headers
        current: Original file content
        rendered: New/expected file content

    Returns:
        Unified diff string
    """
    return ''.join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            rendered.splitlines(keepends=True),
            fromfile=rel_path,
            tofile=rel_path,
        ),
    )


def merge_dicts_first_wins(
    dicts: Iterable[Mapping[str, V]],
) -> dict[str, V]:
    """Merge multiple dicts keeping the first occurrence of each key.

    When the same key appears in multiple dicts, the first occurrence wins.
    This is useful for layered configurations where earlier sources take
    precedence.

    Args:
        dicts: Iterable of dicts to merge (e.g., `my_dict.values()`)

    Returns:
        Single merged dict with first-occurrence semantics for duplicate keys

    Example:
        >>> merge_dicts_first_wins([{'a': 1, 'b': 2}, {'b': 3, 'c': 4}])
        {'a': 1, 'b': 2, 'c': 4}
    """
    result: dict[str, V] = {}
    for d in dicts:
        for key, value in d.items():
            result.setdefault(key, value)
    return result
