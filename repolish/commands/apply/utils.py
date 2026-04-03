"""Shared utilities for the commands.apply package."""

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path

from repolish.providers.models import GlobalContext, get_global_context
from repolish.providers.models.context import WorkspaceContext


@contextlib.contextmanager
def chdir(path: Path) -> Iterator[None]:
    """Context manager that temporarily changes the working directory."""
    old = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(old)


def build_global_context(workspace: WorkspaceContext) -> GlobalContext:
    """Return a :class:`GlobalContext` with the given :class:`WorkspaceContext` injected."""
    base = get_global_context()
    return base.model_copy(update={'workspace': workspace})
