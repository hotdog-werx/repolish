from repolish.insertions.provider_resolution import (
    resolve_provider_function_name,
)


def test_resolve_provider_function_name_returns_none_for_non_owner_qualified_key() -> None:
    """A qualified key for another provider is not visible to this provider."""
    result = resolve_provider_function_name(
        'unknown:display-year',
        'p',
        is_first_provider=True,
    )
    assert result is None
