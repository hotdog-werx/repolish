import re

from repolish.processors import _select_capture, _trim_block_by_indent


def test_select_capture_with_group():
    m = re.search(r'(\w+)-(\d+)', 'abc-123')
    assert m is not None
    # when the pattern contains a capture group we prefer group(1)
    assert _select_capture(m) == 'abc'


def test_select_capture_without_group():
    m = re.search(r'\d{3}', 'xyz123foo')
    assert m is not None
    # when there is no capture group we fall back to the full match
    assert _select_capture(m) == '123'


def test_trim_block_by_indent_trims_on_less_indent():
    block = '  - item\n    - sub\n    - sub2\n  - other\n next\n'
    expected = '  - item\n    - sub\n    - sub2\n  - other\n'
    assert _trim_block_by_indent(block) == expected


def test_trim_block_by_indent_preserves_blank_lines():
    block = '  - item\n\n    - sub\n\n  - other\n next\n'
    expected = '  - item\n\n    - sub\n\n  - other\n'
    assert _trim_block_by_indent(block) == expected


def test_trim_block_by_indent_empty_returns_empty():
    assert _trim_block_by_indent('') == ''
