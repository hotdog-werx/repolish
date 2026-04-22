import tomllib
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, cast

from pydantic import BaseModel


@lru_cache(maxsize=128)
def read_toml(path: Path) -> dict[str, Any] | None:
    """Read and parse a TOML file, caching the result by resolved path.

    Returns the parsed dictionary on success, or ``None`` when the file
    cannot be read or parsed (missing file, permission error, decode error).
    The cache is keyed on the resolved path, so the same file is never
    parsed more than once per process.
    """
    try:
        with path.open('rb') as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return None


def ctx_to_dict(ctx: object | None) -> dict[str, object]:
    """Normalize a provider-style context object to a plain dict.

    The value may be a :class:`pydantic.BaseModel` (in which case `model_dump`
    is called) or already a `dict`.  `None` or any other type becomes an
    empty dictionary to avoid leaking unexpected values into rendered
    templates or logs.  This helper is used by both the loader and command
    layers and lives here to avoid duplication.
    """
    if isinstance(ctx, BaseModel):
        return ctx.model_dump()
    if isinstance(ctx, dict):
        return cast('dict[str, object]', ctx)
    return {}


def ctx_keys(ctx_obj: object | None) -> list[str]:
    """Return the keys of a provider-style context object.

    Behaves similarly to :func:`ctx_to_dict` but only returns the top-level
    keys rather than the full mapping.  `BaseModel` instances are converted
    to dicts via `model_dump`.  `None` or unsupported types yield an
    empty list.  This helper is handy when iterating or filtering context
    values without materializing a full dictionary.
    """
    if isinstance(ctx_obj, BaseModel):
        return cast('list[str]', list(ctx_obj.model_dump().keys()))
    if isinstance(ctx_obj, dict):
        return cast('list[str]', list(ctx_obj.keys()))
    return []


def is_conditional_file(path_str: str) -> bool:
    """Check if any component of a path starts with the _repolish. prefix.

    This prefix is used both for conditional template files and for
    temporary mapping outputs written during hydration.  A path is
    considered conditional when its own filename *or* any parent directory
    name begins with `_repolish.`, so an entire subtree of files can be
    treated as staging-only by placing them inside a `_repolish.`-prefixed
    folder — allowing the individual filenames to remain clean.

    Args:
        path_str: POSIX-style relative path

    Returns:
        True if any path component starts with '_repolish.'
    """
    return any(part.startswith('_repolish.') for part in PurePosixPath(path_str).parts)
