from pathlib import PurePosixPath

from repolish.providers import TemplateMapping


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
        src = source_path.source_template
        if src is None:
            return None
        src = src.removesuffix('.jinja')
        # Normalize path separators to POSIX style (forward slashes)
        return PurePosixPath(src).as_posix()
    # pragma: no cover — callers are validated by the SessionBundle model and
    # do not pass None; kept as a belt-and-suspenders guard only.
    if source_path is None:  # pragma: no cover
        return None
    source_path = source_path.removesuffix('.jinja')
    # Normalize path separators to POSIX style (forward slashes)
    return PurePosixPath(source_path).as_posix()
