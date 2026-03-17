from pathlib import Path
from textwrap import dedent

import pytest

from repolish.loader import create_providers
from repolish.loader.models.files import TemplateMapping


def write_provider(tmp_path: Path, src: str) -> str:
    d = tmp_path / 'prov'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'repolish.py').write_text(src)
    return str(d)


def test_create_anchors_wrong_type_raises(tmp_path: Path):
    """create_anchors() returning a non-dict raises TypeError."""
    src = dedent(
        """
        from repolish import BaseContext, Provider, BaseInputs

        class Ctx(BaseContext):
            pass

        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_anchors(self, context=None):
                return ('not', 'a', 'dict')
        """,
    )
    with pytest.raises(TypeError):
        create_providers([write_provider(tmp_path, src)])


def test_delete_files_negation_and_history(tmp_path: Path):
    """A later provider can cancel a delete via FileMode.KEEP and provenance is tracked."""
    src1 = dedent(
        """
        from repolish import BaseContext, Provider, BaseInputs, TemplateMapping, FileMode

        class Ctx(BaseContext):
            pass

        class P1(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_mappings(self, context=None):
                return {'a.txt': TemplateMapping(source_template=None, file_mode=FileMode.DELETE)}
        """,
    )
    src2 = dedent(
        """
        from repolish import BaseContext, Provider, BaseInputs, TemplateMapping, FileMode

        class Ctx(BaseContext):
            pass

        class P2(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_mappings(self, context=None):
                return {
                    'a.txt': TemplateMapping(source_template=None, file_mode=FileMode.KEEP),
                    'b.txt': TemplateMapping(source_template=None, file_mode=FileMode.DELETE),
                }
        """,
    )
    p1 = write_provider(tmp_path / 'p1', src1)
    p2 = write_provider(tmp_path / 'p2', src2)

    providers = create_providers([p1, p2])
    got = {Path(p) for p in providers.delete_files}
    assert Path('b.txt') in got
    assert Path('a.txt') not in got

    # provenance: a.txt last decision should be keep, b.txt delete
    assert providers.delete_history['a.txt'][-1].action.value == 'keep'
    assert providers.delete_history['b.txt'][-1].action.value == 'delete'


def test_file_mappings_none_values_are_filtered(tmp_path: Path):
    """None values returned from create_file_mappings() are silently ignored."""
    src = dedent(
        """
        from repolish import BaseContext, Provider, BaseInputs

        class Ctx(BaseContext):
            pass

        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_mappings(self, context=None):
                return {'dest.txt': None, 'x.txt': 'y.txt'}
        """,
    )
    providers = create_providers([write_provider(tmp_path, src)])
    assert 'dest.txt' not in providers.file_mappings
    tm = providers.file_mappings.get('x.txt')
    assert isinstance(tm, TemplateMapping)
    assert tm.source_template == 'y.txt'
