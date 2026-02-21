from pathlib import PurePosixPath
from typing import cast

from pydantic import BaseModel


def ctx_to_dict(ctx: object | None) -> dict[str, object]:
    """Normalize a provider-style context object to a plain dict.

    The value may be a :class:`pydantic.BaseModel` (in which case ``model_dump``
    is called) or already a ``dict``.  ``None`` or any other type becomes an
    empty dictionary to avoid leaking unexpected values into rendered
    templates or logs.  This helper is used by both the loader and command
    layers and lives here to avoid duplication.
    """
    if isinstance(ctx, BaseModel):
        return ctx.model_dump()
    if isinstance(ctx, dict):
        return cast('dict[str, object]', ctx)
    return {}


def is_conditional_file(path_str: str) -> bool:
    """Check if a file's name starts with the _repolish. prefix.

    Conditional files are those with filenames starting with '_repolish.'
    regardless of where they are in the directory structure (e.g.,
    '_repolish.config.yml' or '.github/workflows/_repolish.ci.yml').

    Args:
        path_str: POSIX-style relative path

    Returns:
        True if the filename starts with '_repolish.'
    """
    filename = PurePosixPath(path_str).name
    return filename.startswith('_repolish.')
