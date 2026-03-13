"""Tests for hydration context building functionality."""

from pathlib import Path
from textwrap import dedent

from repolish.config import RepolishConfig, ResolvedProviderInfo
from repolish.hydration.context import build_final_providers


def test_config_level_provenance(tmp_path: Path):
    """Config-level delete_files (with '!' negation) override provider decisions.

    A provider marks 'a.txt' for deletion via FileMode.DELETE.  The project
    config then negates it (keeping the file) and adds 'b.txt' instead.
    Provenance should record both the provider decision and the config override.
    """
    prov = tmp_path / 'prov'
    prov.mkdir()
    (prov / 'repolish.py').write_text(
        dedent("""
        from repolish import BaseContext, Provider, BaseInputs, TemplateMapping, FileMode

        class Ctx(BaseContext):
            pass

        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_mappings(self, context=None):
                return {'a.txt': TemplateMapping(source_template=None, file_mode=FileMode.DELETE)}
    """),
    )

    cfg = RepolishConfig.model_validate(
        {
            'config_dir': tmp_path,
            'anchors': {},
            'post_process': [],
            # config negates a.txt and adds b.txt
            'delete_files': ['!a.txt', 'b.txt'],
            'providers': {
                'p': ResolvedProviderInfo(
                    alias='p',
                    target_dir=prov,
                    symlinks=[],
                ),
            },
        },
    )

    providers = build_final_providers(cfg)

    got = {Path(p) for p in providers.delete_files}
    assert Path('b.txt') in got
    assert Path('a.txt') not in got

    # Provenance: provider scheduled a.txt for deletion…
    a_hist = providers.delete_history.get('a.txt')
    assert a_hist
    assert len(a_hist) >= 2
    assert a_hist[0].action.value == 'delete'
    # …then config cancelled it
    assert a_hist[-1].source == cfg.config_dir.as_posix()
    assert a_hist[-1].action.value == 'keep'

    # Provenance: b.txt added by config
    b_hist = providers.delete_history.get('b.txt')
    assert b_hist
    assert b_hist[-1].source == cfg.config_dir.as_posix()
    assert b_hist[-1].action.value == 'delete'

    assert isinstance(providers.provider_contexts, dict)


def test_provider_alias_available_in_create_context(tmp_path: Path):
    """Provider.alias is set to the config key before create_context runs."""
    prov = tmp_path / 'prov'
    prov.mkdir()
    (prov / 'repolish.py').write_text(
        dedent("""
        from repolish import BaseContext, Provider, BaseInputs

        class Ctx(BaseContext):
            alias: str = ''

        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx(alias=self.alias)
        """),
    )

    cfg = RepolishConfig.model_validate(
        {
            'config_dir': tmp_path,
            'anchors': {},
            'post_process': [],
            'delete_files': [],
            'providers': {
                'myalias': ResolvedProviderInfo(
                    alias='myalias',
                    target_dir=prov,
                    symlinks=[],
                ),
            },
        },
    )

    providers = build_final_providers(cfg)
    ctx = providers.provider_contexts.get(prov.as_posix())
    assert ctx is not None
    assert getattr(ctx, 'alias', None) == 'myalias'


def test_per_provider_context_override_with_nested_directory(tmp_path: Path):
    """Overrides resolve correctly when the provider resources live in a sub-directory.

    The alias key in ``config.providers`` may point to the parent directory
    while ``target_dir`` points to a nested folder.  ``build_final_providers``
    must use ``target_dir`` as the provider id so that the override is applied
    to the right provider context.
    """
    prov = tmp_path / 'prov'
    prov.mkdir()
    sub = prov / 'templates'
    sub.mkdir()
    (sub / 'repolish.py').write_text(
        dedent("""
        from repolish import BaseContext, Provider, BaseInputs

        class Ctx(BaseContext):
            foo: str = 'orig'

        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()
    """),
    )

    info = ResolvedProviderInfo(
        alias='p',
        target_dir=sub,
        symlinks=[],
        context={'foo': 'override'},
    )
    cfg = RepolishConfig.model_validate(
        {
            'config_dir': tmp_path,
            'anchors': {},
            'post_process': [],
            'delete_files': [],
            'providers': {prov.as_posix(): info},
        },
    )

    providers = build_final_providers(cfg)
    pid = sub.as_posix()
    ctx = providers.provider_contexts.get(pid)
    assert ctx is not None
    ctx_dict = ctx.model_dump()
    assert ctx_dict.get('foo') == 'override'
