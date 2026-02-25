import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import cast

import pytest
from pydantic import BaseModel
from pytest_mock import MockerFixture

from repolish import loader as loader_mod
from repolish.loader import Providers, create_providers
from repolish.loader.module_loader import ModuleProviderAdapter
from repolish.loader.validation import _is_suspicious_variable


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

    assert providers.context == case.expected_context
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


def test_class_based_provider_is_marked_migrated(tmp_path: Path):
    """Providers implemented as a subclass should be considered migrated.

    The loader previously required an explicit ``provider_migrated = True``
    variable; after the change any module that exports a ``Provider``
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

    provider_id = str(p)
    providers = create_providers([provider_id])
    assert providers.provider_migrated.get(provider_id) is True


def test_error_when_module_exports_multiple_provider_classes(tmp_path: Path):
    """A single ``repolish.py`` may not declare more than one Provider subclass.

    Historically the loader silently picked the first class it found, which
    led to confusing behaviour when a file accidentally imported a provider
    for reuse.  Now the loader detects the mistake early and raises a
    ``RuntimeError``.
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
    assert 'multiple Provider subclasses' in str(excinfo.value)


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


def test_loading_reuses_existing_module(tmp_path: Path):
    """Loading a provider file that has already been imported should not create a second module instance.

    This regression manifests as two distinct ``Provider`` classes that
    compare unequal even though they come from the same source.  To simulate
    the real-world case we import the file under a package name before
    calling ``create_providers``.
    """
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    (pkg / '__init__.py').write_text('')

    src = pkg / 'repolish.py'
    src.write_text(
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
    )

    # import the module normally using the package name

    sys.path.insert(0, str(tmp_path))
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
    # ``loaded_cls is normal_cls`` above already proves the loader reused the
    # module.
    _ = create_providers([str(pkg)])
    p0 = tmp_path / 'p0'
    p0.mkdir()
    (p0 / 'repolish.py').write_text(
        dedent(
            """
            # module-style provider
            called = False

            def create_context():
                return {}

            def provide_inputs(ctx, allp, idx):
                global called
                called = True
                return []
            """,
        ),
    )

    p1 = tmp_path / 'p1'
    p1.mkdir()
    (p1 / 'repolish.py').write_text('\ndef create_context():\n    return {}\n')

    # spy on the adapter method so we can detect the call regardless of
    # how the provider was imported / named.
    count = 0
    orig = ModuleProviderAdapter.provide_inputs

    def spy(self, own_context, all_providers, provider_index):  # noqa: ANN001, ANN202 - spy for method
        nonlocal count
        count += 1
        return orig(self, own_context, all_providers, provider_index)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(ModuleProviderAdapter, 'provide_inputs', spy)

    _ = create_providers([str(p0), str(p1)])
    monkeypatch.undo()

    assert count >= 1, 'provide_inputs was not called on module provider p0'


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

    assert providers.context == case.expected_context
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
    assert providers.context == {'a': 1}
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
    assert any(call.kwargs.get('provider') == str(provider_dir) for call in warning_calls)


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
