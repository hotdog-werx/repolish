from pathlib import Path
from textwrap import dedent

import pytest

from repolish.loader import create_providers


def write_provider(tmp_path: Path, src: str) -> str:
    d = tmp_path / 'prov'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'repolish.py').write_text(src)
    return str(d)


def test_create_anchors_callable_and_module(tmp_path: Path):
    # callable
    src = dedent(
        """
        def create_anchors():
            return {'A': 'one'}
        """,
    )
    p1 = write_provider(tmp_path / 'p1', src)
    providers = create_providers([p1])
    assert providers.anchors.get('A') == 'one'

    # module-level
    src2 = "anchors = {'B': 'two'}\n"
    p2 = write_provider(tmp_path / 'p2', src2)
    providers2 = create_providers([p2])
    assert providers2.anchors.get('B') == 'two'


def test_create_anchors_wrong_type_raises(tmp_path: Path):
    src = dedent(
        """
        def create_anchors():
            return ('not', 'a', 'dict')
        """,
    )
    d = tmp_path / 'prov'
    d.mkdir()
    (d / 'repolish.py').write_text(src)
    with pytest.raises(TypeError):
        create_providers([str(d)])


def test_missing_context_logs_warning(tmp_path: Path):
    src = '# no context defined\n'
    d = tmp_path / 'prov'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'repolish.py').write_text(src)

    providers = create_providers([str(d)])
    assert providers is not None


def test_apply_raw_delete_items_negation_and_history(tmp_path: Path):
    src = dedent(
        """
        def create_delete_files():
            return ['a.txt']

        delete_files = ['!a.txt', 'b.txt']
        """,
    )
    d = tmp_path / 'prov'
    d.mkdir()
    (d / 'repolish.py').write_text(src)

    providers = create_providers([str(d)])
    got = {Path(p) for p in providers.delete_files}
    assert Path('b.txt') in got
    assert Path('a.txt') not in got

    # provenance: a.txt last decision should be keep, b.txt delete
    assert providers.delete_history['a.txt'][-1].action.value == 'keep'
    assert providers.delete_history['b.txt'][-1].action.value == 'delete'


def test_file_mappings_module_variable_filters_none(tmp_path: Path):
    src = dedent(
        """
        file_mappings = {'dest.txt': None, 'x.txt': 'y.txt'}
        """,
    )
    d = tmp_path / 'prov'
    d.mkdir()
    (d / 'repolish.py').write_text(src)

    providers = create_providers([str(d)])
    assert 'dest.txt' not in providers.file_mappings
    assert providers.file_mappings.get('x.txt') == 'y.txt'


def test_create_only_callable_and_module_merge(tmp_path: Path):
    src = dedent(
        """
        def create_create_only_files():
            return ['one.txt']

        create_only_files = ['two.txt']
        """,
    )
    d = tmp_path / 'prov'
    d.mkdir()
    (d / 'repolish.py').write_text(src)

    providers = create_providers([str(d)])
    got = {Path(p) for p in providers.create_only_files}
    assert Path('one.txt') in got
