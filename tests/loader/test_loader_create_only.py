from pathlib import Path
from typing import cast

from repolish.loader.create_only import process_create_only_files


def test_process_create_only_non_iterable_returns_noop():
    # callable returns None -> no changes
    md = cast('dict[str, object]', {'create_create_only_files': lambda: None})
    s = set()
    process_create_only_files(md, {}, s)
    assert s == set()

    # module-level not iterable
    md2 = cast('dict[str, object]', {'create_only_files': None})
    s2 = set()
    process_create_only_files(md2, {}, s2)
    assert s2 == set()


def test_process_create_only_handles_path_items():
    md = cast(
        'dict[str, object]',
        {'create_create_only_files': lambda: [Path('one.txt'), 'two.txt']},
    )
    s = set()
    process_create_only_files(md, {}, s)
    assert Path('one.txt') in s
    assert Path('two.txt') in s
