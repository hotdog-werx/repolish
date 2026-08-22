from repolish.preprocessors.tag_names import (
    is_valid_tag_name,
    parse_section_name,
)


def test_is_valid_tag_name_supports_hyphen() -> None:
    assert is_valid_tag_name('custom-provider-additions')


def test_parse_section_name_accepts_hyphenated_names() -> None:
    assert parse_section_name('[custom-provider-additions]') == 'custom-provider-additions'


def test_parse_section_name_rejects_non_section_lines() -> None:
    assert parse_section_name('custom-provider-additions = ""') is None
