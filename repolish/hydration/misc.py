from pathlib import Path, PurePosixPath

from repolish.providers import TemplateMapping
from repolish.providers.models.template_path import RepolishTemplatePath


def get_source_str_from_mapping(
    source_path: str | TemplateMapping,
) -> str | None:
    """Normalize a mapping value to a source string or return `None`.

    This utility is shared by both `application` and `comparison`
    modules so they don't duplicate the same conditional logic.  The
    value is assumed to have been validated at an earlier stage by the
    `SessionBundle` pydantic model, therefore this function is intentionally
    concise and not defensive beyond the runtime `isinstance` check.

    Trailing ``.jinja`` is stripped here so providers can reference templates
    by their full on-disk name (e.g. ``_repolish.mise.toml.jinja``) or by the
    rendered name (``_repolish.mise.toml``) — repolish strips the suffix when
    staging, so both spellings resolve to the same file.

    Path separators are normalized to forward slashes (POSIX style) so that
    mappings work consistently across platforms. This allows providers to use
    either forward or backslash separators in source paths.
    """
    if isinstance(source_path, TemplateMapping):
        # Use TemplateMapping's built-in logical_name property
        if source_path.logical_name is None:
            return None
        # Normalize path separators to POSIX style (forward slashes)
        return PurePosixPath(source_path.logical_name).as_posix()
    # pragma: no cover — callers are validated by the SessionBundle model and
    # do not pass None; kept as a belt-and-suspenders guard only.
    if source_path is None:  # pragma: no cover
        return None
    # Use RepolishTemplatePath to handle .jinja extension transparently
    return PurePosixPath(
        RepolishTemplatePath.from_string(source_path).logical_name,
    ).as_posix()


def mapping_source_candidates(
    setup_output: Path,
    source_path: str,
) -> list[Path]:
    """Return probe paths for a rendered mapping source.

    The render tree may contain either logical names or explicit ``.jinja``
    names, and mapping materialization uses ``_repolish.`` prefixed files.
    Probe all compatible variants in deterministic order.
    """
    prefix = '_repolish.'
    source_rel = Path(source_path)
    base = setup_output / 'repolish' / source_rel
    parent = setup_output / 'repolish' / source_rel.parent
    name = source_rel.name
    return [
        base,
        parent / f'{name}.jinja',
        parent / f'{prefix}{name}',
        parent / f'{prefix}{name}.jinja',
    ]


def resolve_mapping_source_file(
    setup_output: Path,
    source_path: str,
) -> Path | None:
    """Resolve the first existing rendered mapping source path."""
    for candidate in mapping_source_candidates(setup_output, source_path):
        if candidate.exists():
            return candidate
    return None


def write_mode_from(dest: Path, content: str, *, mode_source: Path) -> None:
    r"""Write *content* to *dest* (UTF-8) in *mode_source*'s permission bits.

    The write is byte-exact (`newline=''`): `\n` never translates to
    `os.linesep` (CRLF on Windows), so repolish output is identical on
    every platform. The full mode is inherited from the original file
    the content came from: without the chmod a staged file is created
    with the process default, an executable template (`setup.sh`,
    provider tools) lands unexecutable, and the apply tier's copy then
    propagates the default mode into the project. The mode is captured
    before anything is written, so a vanished original fails without
    touching *dest*.

    Sibling of :func:`repolish.marker_kit.write_mode_preserved`, which
    restores a file's own mode for in-place marker writes; this one is
    for fresh files whose mode lives on the original they render from.
    """
    mode = mode_source.stat().st_mode
    dest.write_text(content, encoding='utf-8', newline='')
    dest.chmod(mode)
