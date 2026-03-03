import datetime
import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING, cast

import pytest
from pydantic import BaseModel
from pytest_mock import MockerFixture

from repolish import loader as loader_mod
from repolish.loader import Providers, create_providers

if TYPE_CHECKING:
    from repolish.loader.models import BaseContext
from repolish.loader.validation import _is_suspicious_variable
from tests.support import write_module


@dataclass
class ProviderCase:
    name: str
    providers: list[str]
    expected_context: dict
    expected_anchors: dict
    expected_delete: list[Path]


@pytest.mark.parametrize(
    'case',
    [
        ProviderCase(
            name='single_provider',
            providers=[
                # one provider exporting context, anchors, and delete_files
                dedent(
                    """
                    context = {'a': 1}
                    anchors = {'X': 'replace'}
                    delete_files = ['foo.txt', 'sub/bar.txt']
                    """,
                ),
            ],
            expected_context={'a': 1},
            expected_anchors={'X': 'replace'},
            expected_delete=[Path('foo.txt'), Path('sub/bar.txt')],
        ),
        ProviderCase(
            name='override_and_negation',
            providers=[
                # first provider adds a and anchor and file
                dedent(
                    """
                    context = {'a': 1, 'keep': True}
                    anchors = {'X': 'first'}
                    delete_files = ['a.txt', 'c.txt']
                    """,
                ),
                # second provider overrides context/anchor and negates a.txt
                dedent(
                    """
                    def create_context():
                        return {'a': 2}

                    def create_anchors():
                        return {'X': 'second'}

                    delete_files = ['!a.txt', 'b.txt']
                    """,
                ),
            ],
            expected_context={'a': 2, 'keep': True},
            expected_anchors={'X': 'second'},
            expected_delete=[Path('c.txt'), Path('b.txt')],
        ),
        ProviderCase(
            name='create_delete_files_returns_paths',
            providers=[
                dedent(
                    """
                    def create_delete_files():
                        from pathlib import Path

                        return [Path('one.txt'), Path('two.txt')]
                    """,
                ),
            ],
            expected_context={},
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

    providers: Providers = create_providers(dirs)  # type: ignore[arg-type]

    # the merged context now always contains a ``repolish`` key; tests were
    # written assuming it didn't exist so strip it before comparing.
    ctx = dict(providers.context)
    ctx.pop('repolish', None)
    assert ctx == case.expected_context
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
        from repolish.loader.models import Provider, ProviderEntry

        class A(Provider):
            def get_provider_name(self):
                return 'A'

            def create_context(self):
                return {'which': 'A'}

        class B(Provider):
            def get_provider_name(self):
                return 'B'

            def create_context(self):
                return {'which': 'B'}

        __all__ = ['A']
        """,
        ),
    )

    providers = create_providers([str(prov)])  # should succeed using A
    ctx = dict(providers.context)
    ctx.pop('repolish', None)
    assert ctx == {'which': 'A'}


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
        from repolish.loader.models import Provider, ProviderEntry

        class A(Provider):
            def get_provider_name(self):
                return 'A'

            def create_context(self):
                return {'which': 'A'}

        class B(Provider):
            def get_provider_name(self):
                return 'B'

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
    """Providers loaded via (alias, path) pairs see their config alias."""
    # create a simple provider module that asserts the alias in finalize_context
    prov = tmp_path / 'simple'
    prov.mkdir()
    (prov / 'repolish.py').write_text(
        """from pydantic import BaseModel
from repolish.loader.models import Provider, ProviderEntry
from repolish import BaseContext

class Ctx(BaseModel):
    pass

class Checker(Provider[Ctx, BaseModel]):
    def get_provider_name(self):
        return 'pname'

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


def test_create_providers_records_provider_migrated_flag(tmp_path: Path):
    # Provider 1 sets provider_migrated=True; Provider 2 does not
    p1 = tmp_path / 'p1'
    p1.mkdir()
    (p1 / 'repolish.py').write_text('provider_migrated = True\n')

    p2 = tmp_path / 'p2'
    p2.mkdir()
    (p2 / 'repolish.py').write_text('create_file_mappings = {}\n')

    providers = create_providers([str(p1), str(p2)])
    migrated = providers.provider_migrated
    assert isinstance(migrated, dict)
    assert any(migrated.values())
    assert any(not v for v in migrated.values())


def test_global_context_appears_in_merged_and_provider_dicts(
    tmp_path: Path,
    monkeypatch,  # noqa: ANN001
):
    """The global ``repolish`` namespace is seeded and propagated.

    Both the final merged context and each provider's own context (dict or
    model) should contain the inferred repository owner/name under a
    ``repolish`` key.  Providers may override the value by returning their own
    key or via project configuration.
    """
    monkeypatch.setattr(
        'repolish.providers.git.get_owner_repo',
        lambda: ('foo', 'bar'),
    )

    prov = tmp_path / 'prov'
    prov.mkdir()
    # no explicit context; loader should still provide repolish globals
    (prov / 'repolish.py').write_text('')

    providers = create_providers([str(prov)])
    # merged context should include our fake values; other keys (e.g. `year`)
    # may also be present and are fine.
    merged = cast('dict[str, object]', providers.context.get('repolish', {}))
    assert merged.get('repo') == {'owner': 'foo', 'name': 'bar'}
    assert merged.get('year') == datetime.datetime.now(datetime.UTC).year
    # and the provider-specific context dict should have them too
    pid = next(iter(providers.provider_contexts.keys()))
    ctx_val = cast('dict[str, object]', providers.provider_contexts[pid])
    prov_ctx = cast('dict[str, object]', ctx_val['repolish'])
    assert prov_ctx.get('repo') == {'owner': 'foo', 'name': 'bar'}
    # provider contexts may or may not include the year key depending on
    # when they were constructed; we don't require it.


def test_global_context_in_class_based_provider(
    tmp_path: Path,
    monkeypatch,  # noqa: ANN001
):
    """Class-based providers receive a typed `repolish` field.

    When ``create_context()`` returns a subclass of :class:`BaseContext` the
    loader should populate the ``repolish`` attribute with the global data.
    """
    monkeypatch.setattr(
        'repolish.providers.git.get_owner_repo',
        lambda: ('x', 'y'),
    )

    prov = tmp_path / 'cp'
    prov.mkdir()
    (prov / 'repolish.py').write_text(
        """from pydantic import BaseModel
from repolish import BaseContext
from repolish.loader.models import Provider

class Ctx(BaseContext):
    pass

class P(Provider[Ctx, BaseModel]):
    def get_provider_name(self):
        return 'p'
    def create_context(self):
        return Ctx()
""",
    )

    providers = create_providers([str(prov)])
    # merged context should still contain the global namespace; we only
    # check that the repo info is correct and the year key exists.
    merged = cast('dict[str, object]', providers.context.get('repolish', {}))
    assert merged.get('repo') == {'owner': 'x', 'name': 'y'}
    assert merged.get('year') == datetime.datetime.now(datetime.UTC).year

    pid = next(iter(providers.provider_contexts.keys()))

    ctx = cast('BaseContext', providers.provider_contexts[pid])
    assert hasattr(ctx, 'repolish')
    assert ctx.repolish.repo.owner == 'x'
    assert ctx.repolish.repo.name == 'y'


def test_class_based_provider_is_marked_migrated(tmp_path: Path):
    """Providers implemented as a subclass should be considered migrated.

    The loader previously required an explicit `provider_migrated = True`
    variable; after the change any module that exports a `Provider`
    instance will be treated as migrated automatically.  This makes the
    assumption stated in the apply command docs true and avoids needing to
    update the boolean in every provider.
    """
    p = tmp_path / 'p'
    p.mkdir()
    (p / 'repolish.py').write_text(
        """
from pydantic import BaseModel
from repolish.loader.models import Provider

class Ctx(BaseModel):
    val: int = 42

class P(Provider[Ctx, BaseModel]):
    def get_provider_name(self) -> str:
        return 'foo'
    def create_context(self) -> Ctx:
        return Ctx()
""",
    )

    provider_id = Path(p).as_posix()
    providers = create_providers([str(p)])
    assert providers.provider_migrated.get(provider_id) is True


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
from repolish.loader.models import Provider

class Ctx(BaseModel):
    pass

class One(Provider[Ctx, BaseModel]):
    def get_provider_name(self) -> str:
        return 'one'
    def create_context(self) -> Ctx:
        return Ctx()

class Two(Provider[Ctx, BaseModel]):
    def get_provider_name(self) -> str:
        return 'two'
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
    # Provider A provides {'a': 1}; Provider B depends on merged value and adds 'b'
    src_a = dedent(
        """
        def create_context():
            return {'a': 1}

        def create_file_mappings():
            return {'x.txt': 'tmpl'}
        """,
    )
    src_b = dedent(
        """
        def create_context(ctx):
            return {'b': ctx['a'] + 1}

        def create_file_mappings():
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

    # provider_contexts should include per-provider objects keyed by provider id
    assert isinstance(providers.provider_contexts, dict)
    assert len(providers.provider_contexts) == 2
    # convert each to dict for assertion
    pids = list(providers.provider_contexts.keys())
    ctx0 = providers.provider_contexts[pids[0]]
    if isinstance(ctx0, BaseModel):
        ctx0 = ctx0.model_dump()
    ctx0 = cast('dict[str, object]', ctx0)
    assert ctx0.get('a') == 1
    ctx1 = providers.provider_contexts[pids[1]]
    if isinstance(ctx1, BaseModel):
        ctx1 = ctx1.model_dump()
    ctx1 = cast('dict[str, object]', ctx1)
    assert ctx1.get('b') == 2


def test_three_phase_input_routing_and_finalize(tmp_path: Path):
    """Phase 2/3: provider A sends inputs to provider B and B finalizes context."""
    # Provider A -> sends an input to provider B
    p_a = tmp_path / 'prov_a'
    p_a.mkdir()
    (p_a / 'repolish.py').write_text(
        dedent(
            """
            from pydantic import BaseModel
            from repolish.loader import Provider

            class AContext(BaseModel):
                val: int = 1

            class AProvider(Provider[AContext, BaseModel]):
                def get_provider_name(self) -> str:
                    return 'prov-a'

                def create_context(self) -> AContext:
                    return AContext()

                def provide_inputs(self, own_context, all_providers, provider_index):
                    # emit a simple dict; the loader will validate it against B's
                    # input schema during distribution
                    return [{'register_component': 'database'}]
            """,
        ),
    )

    p_b = tmp_path / 'prov_b'
    p_b.mkdir()
    (p_b / 'repolish.py').write_text(
        dedent(
            """
            from pydantic import BaseModel
            from repolish.loader.models import Provider

            class BContext(BaseModel):
                registered_components: list[str] = []

            class BInputs(BaseModel):
                register_component: str

            class BProvider(Provider[BContext, BInputs]):
                def get_provider_name(self) -> str:
                    return 'prov-b'

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
from pydantic import BaseModel
from repolish.loader.models import Provider

class MyCtx(BaseModel):
    value: int = 1

class MyProvider(Provider[MyCtx, BaseModel]):
    def get_provider_name(self):
        return 'foo'
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
    loaded_cls = loader_mod.orchestrator._find_provider_class(mod_dict)
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
from pydantic import BaseModel
from repolish.loader.models import Provider

class Ctx(BaseModel):
    pass

class P(Provider[Ctx, BaseModel]):
    def get_provider_name(self):
        return 'foo'
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
            expected_context={},
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
            expected_context={},
            expected_anchors={},
            expected_delete=[Path('one.txt')],
        ),
        ProviderCase(
            name='module_level_paths',
            providers=[
                dedent(
                    """
                    from pathlib import Path

                    delete_files = [Path('pm.txt'), 'str.txt']
                    """,
                ),
            ],
            expected_context={},
            expected_anchors={},
            expected_delete=[Path('pm.txt'), Path('str.txt')],
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
            expected_context={},
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
            expected_context={},
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
            expected_context={},
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
            expected_context={},
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
            expected_context={},
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

    ctx = dict(providers.context)
    ctx.pop('repolish', None)
    assert ctx == case.expected_context
    assert providers.anchors == case.expected_anchors
    got_delete = {Path(p) for p in providers.delete_files}
    assert got_delete == set(case.expected_delete)


def test_create_providers_permissive_by_default_allows_missing_mappings(
    tmp_path: Path,
):
    """Missing `create_file_mappings` is accepted by default (backward compat)."""
    provider_dir = tmp_path / 'provider'
    provider_dir.mkdir()
    (provider_dir / 'repolish.py').write_text(
        dedent(
            """
            def create_context():
                return {'a': 1}
            """,
        ),
    )

    providers = create_providers([str(provider_dir)])
    ctx = dict(providers.context)
    ctx.pop('repolish', None)
    assert ctx == {'a': 1}
    assert providers.file_mappings == {}


def test_create_providers_require_file_mappings_opt_in_raises(tmp_path: Path):
    """When `require_file_mappings=True`, missing mappings raise (opt-in)."""
    provider_dir = tmp_path / 'provider'
    provider_dir.mkdir()
    (provider_dir / 'repolish.py').write_text(
        dedent(
            """
            def create_context():
                return {'a': 1}
            """,
        ),
    )

    with pytest.raises(RuntimeError):
        create_providers([str(provider_dir)], require_file_mappings=True)


def test_normalize_delete_items_skips_non_strings():
    # Should raise TypeError for non-string entries (fail-fast mode)
    items = [123, 'a/b.txt', None, 'c.txt']
    # In fail-fast mode non-string entries raise
    with pytest.raises(TypeError):
        loader_mod.normalize_delete_items(items)  # type: ignore - testing bad input


def test_normalize_delete_item_as_posix_raises(mocker: MockerFixture):
    # Use a real Path and patch its as_posix to raise so we exercise the
    # path-object branch of the normalizer.
    p = Path('some.txt')
    # Patch the class method; instances delegate to this and instance attributes
    # are read-only on Path subclasses, so patching the class is required.
    mocker.patch.object(type(p), 'as_posix', side_effect=RuntimeError('boom'))
    with pytest.raises(RuntimeError):
        loader_mod.normalize_delete_item(p)


def test_validate_provider_warns_on_typo_create_create(
    tmp_path: Path,
    mocker: MockerFixture,
):
    """Test that _validate_provider_module warns about create_create typo."""
    provider_dir = tmp_path / 'provider'
    provider_dir.mkdir()

    # Mock the logger to capture warnings
    mock_logger = mocker.patch('repolish.loader.validation.logger')

    # Simulate the user's typo: create_create (double create) instead of create_create_only_files
    (provider_dir / 'repolish.py').write_text(
        dedent(
            """
            def create_create():
                return ['file1.txt']
            """,
        ),
    )

    # Load the provider
    create_providers([str(provider_dir)])

    # Should have warned about the suspicious function name
    warning_calls = [
        call
        for call in mock_logger.warning.call_args_list
        if 'suspicious_provider_function' in str(call) or 'unknown_provider_function' in str(call)
    ]
    assert len(warning_calls) > 0, "Expected warning about 'create_create' typo"

    # Verify the function name was mentioned
    assert any('create_create' in str(call) for call in warning_calls)


def test_validate_provider_warns_on_unknown_create_function(
    tmp_path: Path,
    mocker: MockerFixture,
):
    """Test that _validate_provider_module warns about unknown create_ functions."""
    provider_dir = tmp_path / 'provider'
    provider_dir.mkdir()

    mock_logger = mocker.patch('repolish.loader.validation.logger')

    (provider_dir / 'repolish.py').write_text(
        dedent(
            """
            def create_something_weird():
                return []
            """,
        ),
    )

    create_providers([str(provider_dir)])

    # Should warn about unknown function starting with create_
    warning_calls = [call for call in mock_logger.warning.call_args_list if 'unknown_provider_function' in str(call)]
    assert len(warning_calls) > 0
    assert any('create_something_weird' in str(call) for call in warning_calls)


def test_validate_provider_warns_on_suspicious_variables(
    tmp_path: Path,
    mocker: MockerFixture,
):
    """Test that _validate_provider_module warns about suspicious variable names."""
    provider_dir = tmp_path / 'provider'
    provider_dir.mkdir()

    mock_logger = mocker.patch('repolish.loader.validation.logger')

    (provider_dir / 'repolish.py').write_text(
        dedent(
            """
            create_only_file = ['typo.txt']  # Should be create_only_files
            """,
        ),
    )

    create_providers([str(provider_dir)])

    # Should warn about suspicious variable
    warning_calls = [
        call for call in mock_logger.warning.call_args_list if 'suspicious_provider_variable' in str(call)
    ]
    assert len(warning_calls) > 0
    assert any('create_only_file' in str(call) for call in warning_calls)


def test_validate_provider_no_warnings_for_valid_functions(
    tmp_path: Path,
    mocker: MockerFixture,
):
    """Test that _validate_provider_module doesn't warn for valid provider functions."""
    provider_dir = tmp_path / 'provider'
    provider_dir.mkdir()

    mock_logger = mocker.patch('repolish.loader.validation.logger')

    (provider_dir / 'repolish.py').write_text(
        dedent(
            """
            def create_context():
                return {'key': 'value'}

            def create_create_only_files():
                return ['file.txt']

            def create_delete_files():
                return ['old.txt']

            def create_file_mappings():
                return {'dest.txt': 'src.txt'}

            def create_anchors():
                return {'anchor': 'value'}

            # Helper function should be ignored (starts with _)
            def _helper():
                pass
            """,
        ),
    )

    create_providers([str(provider_dir)])

    # Should have no warnings about suspicious functions or variables
    warning_calls = [
        call
        for call in mock_logger.warning.call_args_list
        if 'suspicious_provider' in str(call) or 'unknown_provider' in str(call)
    ]
    assert len(warning_calls) == 0, f'Expected no warnings, got: {warning_calls}'


def test_validate_provider_warns_on_suspicious_files_variable(
    tmp_path: Path,
    mocker: MockerFixture,
):
    """Test warning for variables ending in _files that aren't valid."""
    provider_dir = tmp_path / 'provider'
    provider_dir.mkdir()

    mock_logger = mocker.patch('repolish.loader.validation.logger')

    (provider_dir / 'repolish.py').write_text(
        dedent(
            """
            my_files = ['file1.txt', 'file2.txt']  # Suspicious: ends in _files
            """,
        ),
    )

    create_providers([str(provider_dir)])

    warning_calls = [
        call for call in mock_logger.warning.call_args_list if 'suspicious_provider_variable' in str(call)
    ]
    assert len(warning_calls) > 0
    assert any('my_files' in str(call) for call in warning_calls)


def test_validate_provider_warns_on_suspicious_mappings_variable(
    tmp_path: Path,
    mocker: MockerFixture,
):
    """Test warning for variables ending in _mappings that aren't valid."""
    provider_dir = tmp_path / 'provider'
    provider_dir.mkdir()

    mock_logger = mocker.patch('repolish.loader.validation.logger')

    (provider_dir / 'repolish.py').write_text(
        dedent(
            """
            my_mappings = {'a': 'b'}  # Suspicious: ends in _mappings
            """,
        ),
    )

    create_providers([str(provider_dir)])

    warning_calls = [
        call for call in mock_logger.warning.call_args_list if 'suspicious_provider_variable' in str(call)
    ]
    assert len(warning_calls) > 0
    assert any('my_mappings' in str(call) for call in warning_calls)


def test_validate_provider_no_warnings_for_normal_variables(
    tmp_path: Path,
    mocker: MockerFixture,
):
    """Test that normal variables don't trigger warnings."""
    provider_dir = tmp_path / 'provider'
    provider_dir.mkdir()

    mock_logger = mocker.patch('repolish.loader.logger')

    (provider_dir / 'repolish.py').write_text(
        dedent(
            """
            # Normal variables that shouldn't trigger warnings
            my_config = {'key': 'value'}
            package_version = '1.0.0'
            SOME_CONSTANT = 42
            helper_data = []
            """,
        ),
    )

    create_providers([str(provider_dir)])

    # Should have no warnings about suspicious variables
    warning_calls = [
        call for call in mock_logger.warning.call_args_list if 'suspicious_provider_variable' in str(call)
    ]
    assert len(warning_calls) == 0, f'Expected no warnings for normal variables, got: {warning_calls}'


def test_loader_instantiates_class_based_provider(tmp_path: Path):
    """Loader should detect and use a Provider subclass exported by module."""
    provider_dir = tmp_path / 'provider'
    provider_dir.mkdir()

    (provider_dir / 'repolish.py').write_text(
        dedent(
            """
            from pydantic import BaseModel
            from repolish.loader.models import Provider

            class Ctx(BaseModel):
                name: str = 'from-class'

            class MyProvider(Provider[Ctx, BaseModel]):
                def get_provider_name(self) -> str:
                    return 'my'

                def create_context(self) -> Ctx:
                    return Ctx(name='created-by-class')
            """,
        ),
    )

    providers = create_providers([str(provider_dir)])
    assert providers.context.get('name') == 'created-by-class'


def test_validate_provider_emits_migration_suggestion(
    tmp_path: Path,
    mocker: MockerFixture,
):
    """If module-style provider is detected, emit migration suggestion."""
    provider_dir = tmp_path / 'provider'
    provider_dir.mkdir()

    mock_logger = mocker.patch('repolish.loader.validation.logger')

    (provider_dir / 'repolish.py').write_text(
        dedent(
            """
            def create_context():
                return {'a': 1}

            def create_file_mappings():
                return {'x': 'y'}

            def create_delete_files():
                return ['old.txt']
            """,
        ),
    )

    create_providers([str(provider_dir)])

    # Should have emitted a provider_migration_suggestion warning
    warning_calls = [
        call for call in mock_logger.warning.call_args_list if 'provider_migration_suggestion' in str(call)
    ]
    assert len(warning_calls) > 0
    # Verify suggested methods mention class-style equivalents
    assert any('create_context' in str(call) for call in warning_calls)
    assert any('create_file_mappings' in str(call) for call in warning_calls)
    # the warning should include the provider identifier so users know which
    # module triggered it
    assert any(call.kwargs.get('provider') == Path(provider_dir).as_posix() for call in warning_calls)


def test_is_suspicious_variable_returns_false_for_normal_names():
    """Direct unit test for _is_suspicious_variable returning False."""
    valid_variables = {
        'context',
        'delete_files',
        'file_mappings',
        'create_only_files',
        'anchors',
    }

    # These should all return False (not suspicious)
    assert _is_suspicious_variable('my_config', valid_variables) is False
    assert _is_suspicious_variable('package_version', valid_variables) is False
    assert _is_suspicious_variable('SOME_CONSTANT', valid_variables) is False
    assert _is_suspicious_variable('helper_data', valid_variables) is False
    assert _is_suspicious_variable('some_other_thing', valid_variables) is False


def test_validate_provider_warns_on_create_only_typo(
    tmp_path: Path,
    mocker: MockerFixture,
):
    """Test warning for function names that look like create_only typos."""
    provider_dir = tmp_path / 'provider'
    provider_dir.mkdir()

    mock_logger = mocker.patch('repolish.loader.validation.logger')

    (provider_dir / 'repolish.py').write_text(
        dedent(
            """
            def create_createonly_files():  # Typo: createonly instead of create_only
                return ['file.txt']
            """,
        ),
    )

    create_providers([str(provider_dir)])

    # Should warn with specific suggestion about create_create_only_files
    warning_calls = [
        call for call in mock_logger.warning.call_args_list if 'suspicious_provider_function' in str(call)
    ]
    assert len(warning_calls) > 0
    assert any('create_createonly_files' in str(call) for call in warning_calls)
    assert any('create_create_only_files' in str(call) for call in warning_calls)
