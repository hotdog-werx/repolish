"""Jinja-aware template path helper.

Provides :class:`RepolishTemplatePath` to handle template paths transparently,
regardless of whether the `.jinja` extension is specified.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class RepolishTemplatePath:
    """A Jinja-aware template path wrapper.

    This class wraps a template path and provides methods to handle the
    `.jinja` extension transparently. Whether the developer specifies
    `README.md` or `README.md.jinja`, this class treats them as the same
    logical template file.

    The class provides:
    - ``logical_name``: the destination filename (without `.jinja`)
    - ``real_path``: resolves the actual file on disk, trying both variants
    - ``matches()``: compare two paths by their logical name

    Example::

        tpl = RepolishTemplatePath('README.md.jinja')
        assert tpl.logical_name == 'README.md'

        tpl2 = RepolishTemplatePath('README.md')
        assert tpl == tpl2  # Same logical template

        # Resolve actual file on disk
        src_path = tpl.resolve_source_path(template_dir)
    """

    specified_path: str

    @property
    def has_jinja_suffix(self) -> bool:
        """Whether the specified path ends with `.jinja`."""
        return self.specified_path.endswith('.jinja')

    @classmethod
    def from_string(cls, path: str) -> RepolishTemplatePath:
        """Create a RepolishTemplatePath from a string path."""
        return cls(specified_path=path)

    @classmethod
    def from_path(cls, path: Path) -> RepolishTemplatePath:
        """Create a RepolishTemplatePath from a Path object."""
        return cls(specified_path=path.as_posix())

    @property
    def logical_name(self) -> str:
        """The logical name without the `.jinja` suffix.

        This is the destination filename that will be written to disk.
        For example, both `README.md.jinja` and `README.md` return `README.md`.
        """
        return self.specified_path.removesuffix('.jinja')

    def resolve_source_path(self, template_dir: Path) -> Path | None:
        """Resolve the actual source file path on disk.

        Tries the specified path first, then falls back to the `.jinja`
        variant if the exact path doesn't exist.

        Args:
            template_dir: The base template directory to search under.

        Returns:
            The resolved Path if found, None otherwise.
        """
        # Try the exact specified path first
        exact_path = template_dir / self.specified_path
        if exact_path.exists():
            return exact_path

        # If the specified path doesn't have .jinja, try adding it
        if not self.has_jinja_suffix:
            jinja_path = template_dir / f'{self.specified_path}.jinja'
            if jinja_path.exists():
                return jinja_path

        # If the specified path has .jinja, try without it
        if self.has_jinja_suffix:
            no_jinja_path = template_dir / self.logical_name
            if no_jinja_path.exists():
                return no_jinja_path

        return None
