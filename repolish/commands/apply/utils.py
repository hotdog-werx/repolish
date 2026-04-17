"""Shared utilities for the commands.apply package."""

import contextlib
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from repolish.providers.models import GlobalContext, get_global_context
from repolish.providers.models.context import WorkspaceContext


@dataclass
class CoordinateOptions:
    """Run-time options threaded through all coordinate_sessions helpers."""

    check_only: bool
    strict: bool = False
    member: str | None = None
    root_only: bool = False
    skip_post_process: bool = field(default=False)


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
