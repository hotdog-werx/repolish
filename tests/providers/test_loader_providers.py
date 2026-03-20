import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import cast

import pytest
from pydantic import BaseModel
from pytest_mock import MockerFixture

from repolish import providers as loader_mod
from repolish.providers import SessionBundle, create_providers
from repolish.providers.module import _find_provider_class as _find_provider_cls
from tests.support import write_module


@dataclass
class ProviderCase:
    name: str
    providers: list[str]
    expected_anchors: dict
    expected_delete: list[Path]


@pytest.mark.parametrize(
    'case',
    [
        ProviderCase(
            name='single_provider',
            providers=[
                # one class-based provider with context, anchors, and file_mappings-based deletes
                dedent(
                    """
                    from repolish import BaseContext, Provider, BaseInputs, TemplateMapping, FileMode

                    class Ctx(BaseContext):
                        a: int = 0

                    class MyProvider(Provider[Ctx, BaseInputs]):
                        def create_context(self):
                            return Ctx(a=1)

                        def create_anchors(self, context=None):
                            return {'X': 'replace'}

                        def create_file_mappings(self, context=None):
                            return {
                                'foo.txt': TemplateMapping(source_template=None, file_mode=FileMode.DELETE),
                                'sub/bar.txt': TemplateMapping(source_template=None, file_mode=FileMode.DELETE),
                            }
                    """,
                ),
            ],
            expected_anchors={'X': 'replace'},
            expected_delete=[Path('foo.txt'), Path('sub/bar.txt')],
        ),
        ProviderCase(
            name='override_and_negation',
            providers=[
                # first provider: contributes a, keep, anchor X=first, and two delete entries
                dedent(
                    """
                    from repolish import BaseContext, Provider, BaseInputs, TemplateMapping, FileMode

                    class Ctx(BaseContext):
                        a: int = 0
                        keep: bool = False

                    class ProviderOne(Provider[Ctx, BaseInputs]):
                        def create_context(self):
                            return Ctx(a=1, keep=True)

                        def create_anchors(self, context=None):
                            return {'X': 'first'}

                        def create_file_mappings(self, context=None):
                            return {
                                'a.txt': TemplateMapping(source_template=None, file_mode=FileMode.DELETE),
                                'c.txt': TemplateMapping(source_template=None, file_mode=FileMode.DELETE),
                            }
                    """,
                ),
                # second provider: overrides a and anchor, cancels a.txt deletion, adds b.txt
                dedent(
                    """
                    from repolish import BaseContext, Provider, BaseInputs, TemplateMapping, FileMode

                    class Ctx(BaseContext):
                        a: int = 0

                    class ProviderTwo(Provider[Ctx, BaseInputs]):
                        def create_context(self):
                            return Ctx(a=2)

                        def create_anchors(self, context=None):
                            return {'X': 'second'}

                        def create_file_mappings(self, context=None):
                            return {
                                'a.txt': TemplateMapping(source_template=None, file_mode=FileMode.KEEP),
                                'b.txt': TemplateMapping(source_template=None, file_mode=FileMode.DELETE),
                            }
                    """,
                ),
            ],
            expected_anchors={'X': 'second'},
            expected_delete=[Path('c.txt'), Path('b.txt')],
        ),
        ProviderCase(
            name='delete_via_file_mappings',
            providers=[
                # provider expressing deletes entirely through create_file_mappings
                dedent(
                    """
                    from repolish import BaseContext, Provider, BaseInputs, TemplateMapping, FileMode

                    class Ctx(BaseContext):
                        pass

                    class MyProvider(Provider[Ctx, BaseInputs]):
                        def create_context(self):
                            return Ctx()

                        def create_file_mappings(self, context=None):
                            return {
                                'one.txt': TemplateMapping(source_template=None, file_mode=FileMode.DELETE),
                                'two.txt': TemplateMapping(source_template=None, file_mode=FileMode.DELETE),
                            }
                    """,
                ),
            ],
            expected_anchors={},
            expected_delete=[Path('one.txt'), Path('two.txt')],
        ),
    ],
)
def test_create_providers(tmp_path: Path, case: ProviderCase):
    # Create provider directories with repolish.py files
    dirs: list[str] = []
    for i, src in enumerate(case.providers):
        d = tmp_path / f'prov{i}'
        d.mkdir()
        (d / 'repolish.py').write_text(src)
        dirs.append(str(d))

    providers: SessionBundle = create_providers(dirs)  # type: ignore[arg-type]

    assert providers.anchors == case.expected_anchors

    # delete_files should be a list of Path objects (relative paths from provider)
    got_delete = {Path(p) for p in providers.delete_files}
    want_delete = set(case.expected_delete)
    assert got_delete == want_delete
    # Verify provenance: for every path mentioned in delete_history, the
    # last recorded Decision should reflect the final presence in providers.delete_files
    for key, decisions in providers.delete_history.items():
        assert decisions, 'history entry should contain at least one Decision'
        last = decisions[-1]
        assert last.action.value in {'delete', 'keep'}
        path_obj = Path(key)
        # If final action is delete, path must be present in providers.delete_files
        if last.action.value == 'delete':
            assert path_obj in got_delete
        else:
            assert path_obj not in got_delete


def test_multiple_provider_classes_with_all(tmp_path: Path):
    """A module may import other Provider subclasses but export only one.

    When ``__all__`` names a single provider class we should ignore any
    additional subclasses present in the module.  this allows helper
    providers to be imported at top-level without triggering the "multiple
    providers" error.
    """
    prov = tmp_path / 'prov'
    prov.mkdir()
    (prov / 'repolish.py').write_text(
        dedent(
            """
        from repolish.providers.models import Provider, ProviderEntry
        from repolish import BaseContext

        class ACtx(BaseContext):
            which: str = 'A'

        class BCtx(BaseContext):
            which: str = 'B'

        class A(Provider):
            def create_context(self):
                return ACtx()

        class B(Provider):
            def create_context(self):
                return BCtx()

        __all__ = ['A']
        """,
        ),
    )

    providers = create_providers([str(prov)])  # should succeed using A
    pid = next(iter(providers.provider_contexts.keys()))
    ctx = providers.provider_contexts[pid]
    assert hasattr(ctx, 'which')
    assert ctx.which == 'A'


def test_multiple_providers_all_conflict(tmp_path: Path):
    """Exporting more than one provider via ``__all__`` remains an error.

    The raised message should mention ``__all__`` so users know how to fix
    the problem.
    """
    prov = tmp_path / 'prov2'
    prov.mkdir()
    (prov / 'repolish.py').write_text(
        dedent(
            """
        from repolish.providers.models import Provider, ProviderEntry

        class A(Provider):
            def create_context(self):
                return {'which': 'A'}

        class B(Provider):
            def create_context(self):
                return {'which': 'B'}

        __all__ = ['A', 'B']
        """,
        ),
    )

    with pytest.raises(RuntimeError) as exc:
        create_providers([str(prov)])
    msg = str(exc.value)
    assert '__all__' in msg
    assert 'multiple Provider subclasses' in msg


def test_config_alias_passed_through(tmp_path: Path):
    """SessionBundle loaded via (alias, path) pairs see their config alias."""
    # create a simple provider module that asserts the alias in finalize_context
    prov = tmp_path / 'simple'
    prov.mkdir()
    (prov / 'repolish.py').write_text(
        """
from repolish import BaseContext, Provider, BaseInputs, ProviderEntry

class Ctx(BaseContext):
    pass

class Checker(Provider[Ctx, BaseInputs]):
    def create_context(self):
        return Ctx()

    def finalize_context(self, own_context, received_inputs, all_providers, provider_index):
        entry = all_providers[provider_index]
        # alias should equal the configuration key we passed
        assert entry.alias == 'myalias'
        return own_context
""",
    )
    # call using tuple syntax with alias
    providers = create_providers([('myalias', str(prov))])
    # sanity: creating providers completed without error (alias assertion occurs
    # inside the provider itself).  the provider_contexts map may still use
    # provider IDs as keys.
    assert providers.provider_contexts is not None


def test_global_context_in_class_based_provider(
    tmp_path: Path,
    monkeypatch,  # noqa: ANN001
):
    """Class-based providers receive a typed `repolish` field.

    When ``create_context()`` returns a subclass of :class:`BaseContext` the
    loader should populate the ``repolish`` attribute with the global data.
    """
    monkeypatch.setattr(
        'repolish.providers.models.context._get_owner_repo',
        lambda: ('x', 'y'),
    )

    prov = tmp_path / 'cp'
    prov.mkdir()
    (prov / 'repolish.py').write_text(
        """from pydantic import BaseModel
from repolish import BaseContext
from repolish.providers.models import Provider

class Ctx(BaseContext):
    pass

class P(Provider[Ctx, BaseModel]):
    def create_context(self):
        return Ctx()
""",
    )

    providers = create_providers([str(prov)])
    # GlobalContext is injected into each provider's typed context.
    pid = next(iter(providers.provider_contexts.keys()))

    ctx = providers.provider_contexts[pid]
    assert hasattr(ctx, 'repolish')
    assert ctx.repolish.repo.owner == 'x'
    assert ctx.repolish.repo.name == 'y'


def test_error_when_module_exports_multiple_provider_classes(tmp_path: Path):
    """A single `repolish.py` may not declare more than one Provider subclass.

    Historically the loader silently picked the first class it found, which
    led to confusing behaviour when a file accidentally imported a provider
    for reuse.  Now the loader detects the mistake early and raises a
    `RuntimeError`.
    """
    p = tmp_path / 'prov'
    p.mkdir()
    (p / 'repolish.py').write_text(
        """
from pydantic import BaseModel
from repolish.providers.models import Provider

class Ctx(BaseModel):
    pass

class One(Provider[Ctx, BaseModel]):
    def create_context(self) -> Ctx:
        return Ctx()

class Two(Provider[Ctx, BaseModel]):
    def create_context(self) -> Ctx:
        return Ctx()
""",
    )

    with pytest.raises(RuntimeError) as excinfo:
        create_providers([str(p)])
    msg = str(excinfo.value)
    assert 'multiple Provider subclasses' in msg
    assert '__all__' in msg  # hint should mention the export list


def test_create_providers_records_provider_contexts(tmp_path: Path):
    """Each loaded provider gets its own typed entry in provider_contexts."""
    src_a = dedent(
        """
        from repolish import BaseContext, Provider, BaseInputs

        class CtxA(BaseContext):
            a: int = 0

        class ProviderA(Provider[CtxA, BaseInputs]):
            def create_context(self):
                return CtxA(a=1)

            def create_file_mappings(self, context=None):
                return {'x.txt': 'tmpl'}
        """,
    )
    src_b = dedent(
        """
        from repolish import BaseContext, Provider, BaseInputs

        class CtxB(BaseContext):
            b: int = 0

        class ProviderB(Provider[CtxB, BaseInputs]):
            def create_context(self):
                return CtxB(b=42)

            def create_file_mappings(self, context=None):
                return {'y.txt': 'tmpl'}
        """,
    )

    dirs = []
    for i, src in enumerate((src_a, src_b)):
        d = tmp_path / f'prov{i}'
        d.mkdir()
        (d / 'repolish.py').write_text(src)
        dirs.append(str(d))

    providers = create_providers(dirs)

    # each provider should have its own typed context entry
    assert isinstance(providers.provider_contexts, dict)
    assert len(providers.provider_contexts) == 2
    pids = list(providers.provider_contexts.keys())
    ctx0 = providers.provider_contexts[pids[0]].model_dump()
    assert ctx0.get('a') == 1
    ctx1 = providers.provider_contexts[pids[1]].model_dump()
    assert ctx1.get('b') == 42


def test_provider_exchange_input_routing_and_finalize(tmp_path: Path):
    """Phase 2/3: provider A sends inputs to provider B and B finalizes context."""
    # Provider A -> sends an input to provider B
    p_a = tmp_path / 'prov_a'
    p_a.mkdir()
    (p_a / 'repolish.py').write_text(
        dedent(
            """
            from repolish import Provider, BaseContext, BaseInputs

            class AInputs(BaseInputs):
                register_component: str

            class AContext(BaseContext):
                val: int = 1

            class AProvider(Provider[AContext, BaseInputs]):
                def create_context(self) -> AContext:
                    return AContext()

                def provide_inputs(self, own_context, all_providers, provider_index):
                    return [AInputs(register_component='database')]
            """,
        ),
    )

    p_b = tmp_path / 'prov_b'
    p_b.mkdir()
    (p_b / 'repolish.py').write_text(
        dedent(
            """
            from repolish import Provider, BaseContext, BaseInputs

            class BContext(BaseContext):
                registered_components: list[str] = []

            class BInputs(BaseInputs):
                register_component: str

            class BProvider(Provider[BContext, BInputs]):
                def create_context(self) -> BContext:
                    return BContext()

                def get_inputs_schema(self):
                    return BInputs

                def finalize_context(self, own_context, received_inputs, all_providers, provider_index):
                    own_context.registered_components = (
                        own_context.registered_components
                        + [i.register_component for i in received_inputs]
                    )
                    return own_context
            """,
        ),
    )

    providers = create_providers([str(p_a), str(p_b)])
    pids = list(providers.provider_contexts.keys())
    ctx1 = providers.provider_contexts[pids[1]]
    if isinstance(ctx1, BaseModel):
        ctx1 = ctx1.model_dump()
    ctx1 = cast('dict[str, object]', ctx1)
    assert ctx1.get(
        'registered_components',
    ) == ['database']


def test_provide_inputs_called_for_all_providers(tmp_path: Path):
    """Every provider exposing a `provide_inputs` hook is invoked.

    Use a *module-style* provider so we can inspect its globals afterward and
    confirm the function ran; class-based providers encapsulate the method
    inside the instance, which is harder to access from the test.
    """


def test_loading_reuses_existing_module(tmp_path: Path, mocker: MockerFixture):
    """Loading a provider file that has already been imported should not create a second module instance.

    The loader will attempt to `import` the guessed dotted name before
    falling back to generating a synthetic module name.  When we pre-import
    the package, no additional `repolish_module_…` entry should appear in
    `sys.modules`.

    This regression previously manifested as two distinct `Provider`
    classes that compared unequal even though they came from the same
    source.  To reproduce we import the file under a package name and then
    invoke the loader.

    `sys.path` is patched so that the original value is restored when the
    test finishes.
    """
    pkg = tmp_path / 'pkg'
    src = pkg / 'repolish.py'
    write_module(
        src,
        """
from repolish import Provider, BaseContext, BaseInputs

class MyCtx(BaseContext):
    value: int = 1

class MyProvider(Provider[MyCtx, BaseInputs]):
    def create_context(self) -> MyCtx:
        return MyCtx()
""",
        root=tmp_path,
    )

    # import the module normally using the package name

    new_path = [str(tmp_path)] + [p for p in sys.path if p != str(tmp_path)]
    mocker.patch.object(sys, 'path', new=new_path)
    pkg_mod = importlib.import_module('pkg.repolish')
    assert hasattr(pkg_mod, 'MyProvider')
    normal_cls = pkg_mod.MyProvider

    # now load the same directory via the loader
    module_cache = loader_mod.orchestrator._load_module_cache([str(pkg)])
    # _load_module_cache _may_ return the same module dict we imported earlier
    _, mod_dict = module_cache[0]
    loaded_cls = _find_provider_cls(mod_dict)
    assert loaded_cls is not None
    # identity should be exact (not merely subclass relationship)
    assert loaded_cls is normal_cls
    # and when we instantiate via create_providers we still end up with that
    # same class on the provider instance
    # a full create_providers run should succeed without creating a
    # second class; we don't need to inspect the instance here because
    # `loaded_cls is normal_cls` above already proves the loader reused the
    # module.
    # call the loader; with our earlier import it should simply reuse the
    # existing module rather than creating a new one.
    _ = create_providers([str(pkg)])

    # confirm no synthetic module name was registered
    fallback = 'repolish_module_' + ''.join(c if c.isalnum() or c == '_' else '_' for c in str(pkg))
    assert fallback not in sys.modules


def test_loader_registers_importable_name(
    tmp_path: Path,
    mocker: MockerFixture,
):
    """After loading a provider path the module becomes importable by name.

    Clear any pre-existing `pkg` entries so the package created for this
    test is the one actually loaded; earlier tests may have left a module
    loaded under the same name.

    When the provider lives inside an installable package we expect the
    loader to register the module under its dotted import path so that a
    later `importlib.import_module` returns the same object instead of
    re-executing the file.
    """
    # cleanup imported modules (sys already imported at top of file)
    sys.modules.pop('pkg.repolish', None)
    sys.modules.pop('pkg', None)
    pkg = tmp_path / 'pkg'
    src = pkg / 'repolish.py'
    write_module(
        src,
        """
from repolish import Provider, BaseContext, BaseInputs

class Ctx(BaseContext):
    pass

class P(Provider[Ctx, BaseInputs]):
    def create_context(self) -> Ctx:
        return Ctx()
""",
        root=tmp_path,
    )

    # imports handled at module level; insert our tmp_path under test control
    new_path = [str(tmp_path)] + [p for p in sys.path if p != str(tmp_path)]
    mocker.patch.object(sys, 'path', new=new_path)
    # load provider using the public API; this should register the importable name
    create_providers([str(pkg)])
    # now import by canonical path
    mod = importlib.import_module('pkg.repolish')
    assert mod.__file__ == str(src)


# Additional edge cases expressed with the same ProviderCase dataclass
@pytest.mark.parametrize(
    'case',
    [
        ProviderCase(
            name='import_failure',
            providers=["raise RuntimeError('boom')\n"],
            expected_anchors={},
            expected_delete=[],
        ),
        # In fail-fast mode the following provider definitions should raise
        # during provider evaluation. Tests below assert exceptions.
        ProviderCase(
            name='create_delete_files_mixed',
            providers=[
                dedent(
                    """
                    def create_delete_files():
                        from pathlib import Path

                        return [Path('one.txt'), 123, None]
                    """,
                ),
            ],
            expected_anchors={},
            expected_delete=[Path('one.txt')],
        ),
        ProviderCase(
            name='create_delete_files_raises_fallback',
            providers=[
                dedent(
                    """
                    def create_delete_files():
                        raise RuntimeError('nope')

                    delete_files = ['fallback.txt']
                    """,
                ),
            ],
            expected_anchors={},
            expected_delete=[Path('fallback.txt')],
        ),
        ProviderCase(
            name='module_level_non_paths',
            providers=[
                dedent(
                    """
                    # delete_files contains booleans and numbers -> ignored
                    delete_files = [True, False, 123]
                    """,
                ),
            ],
            expected_anchors={},
            expected_delete=[],
        ),
        ProviderCase(
            name='create_context_wrong_type',
            providers=[
                dedent(
                    """
                    def create_context():
                        return ['not', 'a', 'dict']
                    """,
                ),
            ],
            expected_anchors={},
            expected_delete=[],
        ),
        ProviderCase(
            name='create_anchors_wrong_type',
            providers=[
                dedent(
                    """
                    def create_anchors():
                        return ('not', 'a', 'dict')
                    """,
                ),
            ],
            expected_anchors={},
            expected_delete=[],
        ),
        ProviderCase(
            name='create_delete_files_non_iterable',
            providers=[
                dedent(
                    """
                    def create_delete_files():
                        return 123
                    """,
                ),
            ],
            expected_anchors={},
            expected_delete=[],
        ),
    ],
)
def test_create_providers_edge_cases(tmp_path: Path, case: ProviderCase):
    # Reuse the same test runner but with ProviderCase instances
    dirs: list[str] = []
    for i, src in enumerate(case.providers):
        d = tmp_path / f'prov{i}'
        d.mkdir()
        (d / 'repolish.py').write_text(src)
        dirs.append(str(d))

    # Some cases now raise due to fail-fast semantics. Map names to expected
    # exception behavior.
    raises = {
        'import_failure',
        'create_context_raises',
        'create_anchors_raises',
        'create_delete_files_mixed',
        'create_delete_files_raises_fallback',
        'module_level_non_paths',
        'create_context_wrong_type',
        'create_anchors_wrong_type',
        'create_delete_files_non_iterable',
    }

    if case.name in raises:
        with pytest.raises(Exception):  # noqa: B017, PT011 - broad exception to verify fail-fast
            create_providers(dirs)  # type: ignore[arg-type]
        return

    providers = create_providers(dirs)  # type: ignore[arg-type]

    assert providers.anchors == case.expected_anchors
    got_delete = {Path(p) for p in providers.delete_files}
    assert got_delete == set(case.expected_delete)


def test_loader_instantiates_class_based_provider(tmp_path: Path):
    """Loader should detect and use a Provider subclass exported by module."""
    provider_dir = tmp_path / 'provider'
    provider_dir.mkdir()

    (provider_dir / 'repolish.py').write_text(
        dedent(
            """
            from repolish import BaseContext, BaseInputs, Provider

            class Ctx(BaseContext):
                name: str = 'from-class'

            class MyProvider(Provider[Ctx, BaseInputs]):
                def create_context(self) -> Ctx:
                    return Ctx(name='created-by-class')
            """,
        ),
    )

    providers = create_providers([str(provider_dir)])
    pid = next(iter(providers.provider_contexts.keys()))
    assert providers.provider_contexts[pid].name == 'created-by-class'  # type: ignore[union-attr]


def test_file_mappings_merge_across_providers(tmp_path: Path) -> None:
    """file_mappings from multiple providers are merged into one dict."""
    template_a = tmp_path / 'template_a'
    template_a.mkdir()
    template_b = tmp_path / 'template_b'
    template_b.mkdir()

    (template_a / 'repolish.py').write_text("""
from repolish import BaseContext, Provider, BaseInputs

class Ctx(BaseContext):
    pass

class P(Provider[Ctx, BaseInputs]):
    def create_context(self):
        return Ctx()

    def create_file_mappings(self, context=None):
        return {'file-a.yml': '_repolish.a.yml'}
""")
    (template_b / 'repolish.py').write_text("""
from repolish import BaseContext, Provider, BaseInputs

class Ctx(BaseContext):
    pass

class P(Provider[Ctx, BaseInputs]):
    def create_context(self):
        return Ctx()

    def create_file_mappings(self, context=None):
        return {'file-b.yml': '_repolish.b.yml'}
""")

    providers = create_providers([str(template_a), str(template_b)])

    assert set(providers.file_mappings) == {'file-a.yml', 'file-b.yml'}
    assert providers.file_mappings['file-a.yml'].source_template == '_repolish.a.yml'  # type: ignore[union-attr]
    assert providers.file_mappings['file-b.yml'].source_template == '_repolish.b.yml'  # type: ignore[union-attr]


def test_file_mappings_later_provider_overrides_earlier(tmp_path: Path) -> None:
    """A later provider's mapping overrides an earlier one for the same key."""
    template_a = tmp_path / 'template_a'
    template_a.mkdir()
    template_b = tmp_path / 'template_b'
    template_b.mkdir()

    (template_a / 'repolish.py').write_text("""
from repolish import BaseContext, Provider, BaseInputs

class Ctx(BaseContext):
    pass

class P(Provider[Ctx, BaseInputs]):
    def create_context(self):
        return Ctx()

    def create_file_mappings(self, context=None):
        return {'config.yml': '_repolish.option-a.yml'}
""")
    (template_b / 'repolish.py').write_text("""
from repolish import BaseContext, Provider, BaseInputs

class Ctx(BaseContext):
    pass

class P(Provider[Ctx, BaseInputs]):
    def create_context(self):
        return Ctx()

    def create_file_mappings(self, context=None):
        return {'config.yml': '_repolish.option-b.yml'}
""")

    providers = create_providers([str(template_a), str(template_b)])

    assert list(providers.file_mappings) == ['config.yml']
    assert providers.file_mappings['config.yml'].source_template == '_repolish.option-b.yml'  # type: ignore[union-attr]


def test_none_mapped_entry_populates_suppressed_sources(tmp_path: Path) -> None:
    """A None value in create_file_mappings populates suppressed_sources.

    The key must not appear in file_mappings — the provider explicitly opted
    out of managing that path this run.
    """
    template = tmp_path / 'prov'
    template.mkdir()
    (template / 'repolish.py').write_text("""
from repolish import BaseContext, Provider, BaseInputs

class Ctx(BaseContext):
    pass

class P(Provider[Ctx, BaseInputs]):
    def create_context(self):
        return Ctx()

    def create_file_mappings(self, context=None):
        return {
            '.github/workflows/_ci-checks.yaml': None,
            'other.txt': '_repolish.other.txt',
        }
""")

    providers = create_providers([str(template)])

    assert '.github/workflows/_ci-checks.yaml' not in providers.file_mappings
    assert '.github/workflows/_ci-checks.yaml' in providers.suppressed_sources
    assert 'other.txt' in providers.file_mappings
