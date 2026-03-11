from pathlib import Path
from textwrap import dedent

from pydantic import BaseModel

from repolish.loader import FileMode, TemplateMapping, create_providers


def test_file_mappings_receive_merged_context(tmp_path: Path, monkeypatch):  # noqa: ANN001
    """A provider may use the merged context when creating file mappings.

    This test creates a provider that sets `readme_ext` via `create_context`
    and a `create_file_mappings` factory that builds the destination name
    using that value. The loader should call the factory with the merged
    context so the resulting mapping reflects the configured extension.  We
    also verify that the automatically injected ``repolish`` namespace is
    present in the context passed to the mapping factory.
    """
    # ensure global context is predictable
    monkeypatch.setattr(
        'repolish.providers.git.get_owner_repo',
        lambda: ('owner', 'repo'),
    )

    src = dedent(
        """
        from repolish import BaseContext, Provider, BaseInputs

        class Ctx(BaseContext):
            readme_ext: str = 'txt'

        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_mappings(self, context=None):
                # global context is available via typed attribute
                assert context.repolish.repo.owner == 'owner'
                ext = context.readme_ext
                return {f'README.{ext}': 'README_template'}
        """,
    )

    provider = tmp_path / 'prov'
    provider.mkdir()
    (provider / 'repolish.py').write_text(src)

    providers = create_providers([str(provider)])

    assert providers.file_mappings.get('README.txt') == 'README_template'


def test_create_file_mappings_accepts_pydantic_extra_context(tmp_path: Path):
    """create_file_mappings() may return a `TemplateMapping` with a Pydantic model as extra_context."""
    src = dedent(
        """
        from pydantic import BaseModel
        from repolish import BaseContext, Provider, BaseInputs, TemplateMapping

        class ItemCtx(BaseModel):
            file_number: int

        class Ctx(BaseContext):
            pass

        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_mappings(self, context=None):
                return {'typed.txt': TemplateMapping('template.jinja', ItemCtx(file_number=7))}
        """,
    )

    provider = tmp_path / 'prov'
    provider.mkdir()
    (provider / 'repolish.py').write_text(src)

    providers = create_providers([str(provider)])

    # The mapping should be preserved as a TemplateMapping instance until hydration
    val = providers.file_mappings.get('typed.txt')

    assert isinstance(val, TemplateMapping)
    assert val.source_template == 'template.jinja'
    # extra_context should be a pydantic BaseModel instance
    assert isinstance(val.extra_context, BaseModel)


def test_template_mapping_file_mode_create_only_includes_in_create_only(
    tmp_path: Path,
):
    src = dedent(
        """
        from repolish import BaseContext, Provider, BaseInputs, TemplateMapping, FileMode

        class Ctx(BaseContext):
            pass

        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_mappings(self, context=None):
                return {'a.txt': TemplateMapping('template.jinja', None, FileMode.CREATE_ONLY)}
        """,
    )

    provider = tmp_path / 'prov'
    provider.mkdir()
    (provider / 'repolish.py').write_text(src)

    providers = create_providers([str(provider)])

    # Destination should be marked as create-only and mapping preserved
    assert Path('a.txt') in {Path(p) for p in providers.create_only_files}
    val = providers.file_mappings.get('a.txt')
    assert isinstance(val, TemplateMapping)
    assert val.file_mode == FileMode.CREATE_ONLY


def test_template_mapping_file_mode_delete_marks_for_deletion(tmp_path: Path):
    src = dedent(
        """
        from repolish import BaseContext, Provider, BaseInputs, TemplateMapping, FileMode

        class Ctx(BaseContext):
            pass

        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_mappings(self, context=None):
                return {'old.txt': TemplateMapping(None, None, FileMode.DELETE)}
        """,
    )

    provider = tmp_path / 'prov'
    provider.mkdir()
    (provider / 'repolish.py').write_text(src)

    providers = create_providers([str(provider)])

    # Should be recorded in delete_files and not present in file_mappings
    assert Path('old.txt') in {Path(p) for p in providers.delete_files}
    assert 'old.txt' not in providers.file_mappings
