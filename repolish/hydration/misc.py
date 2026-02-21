from repolish.loader.types import TemplateMapping


def get_source_str_from_mapping(
    source_path: str | TemplateMapping,
) -> str | None:
    """Normalize a mapping value to a source string or return ``None``.

    This utility is shared by both ``application`` and ``comparison``
    modules so they don't duplicate the same conditional logic.  The
    value is assumed to have been validated at an earlier stage by the
    ``Providers`` pydantic model, therefore this function is intentionally
    concise and not defensive beyond the runtime ``isinstance`` check.
    """
    if isinstance(source_path, TemplateMapping):
        return source_path.source_template
    return source_path
