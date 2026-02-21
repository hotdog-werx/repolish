from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

import pytest
from pytest_mock import MockerFixture

from repolish import loader as loader_mod
from repolish.loader import Providers, create_providers
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

    providers: Providers = create_providers(dirs)

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

    # provider_contexts should include per-provider dicts keyed by provider id
    assert isinstance(providers.provider_contexts, dict)
    assert len(providers.provider_contexts) == 2
    # The first provider's context should contain 'a'; second provider's context should contain 'b'
    pids = list(providers.provider_contexts.keys())
    assert providers.provider_contexts[pids[0]].get('a') == 1
    assert providers.provider_contexts[pids[1]].get('b') == 2


def test_three_phase_input_routing_and_finalize(tmp_path: Path):
    """Phase 2/3: provider A sends inputs to provider B and B finalizes context."""
    # Provider A -> sends an input to provider B
    p_a = tmp_path / 'prov_a'
    p_a.mkdir()
    (p_a / 'repolish.py').write_text(
        dedent(
            """
            from pydantic import BaseModel
            from repolish.loader.models import Provider

            class AContext(BaseModel):
                val: int = 1

            class AProvider(Provider[AContext, BaseModel]):
                def get_provider_name(self) -> str:
                    return 'prov-a'

                def create_context(self) -> AContext:
                    return AContext()

                def collect_provider_inputs(self, own_context, all_providers, provider_index):
                    return {'prov-b': {'register_component': 'database'}}
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
    assert providers.provider_contexts[pids[1]].get(
        'registered_components',
    ) == ['database']


def test_collect_provider_inputs_skipped_for_end_providers(tmp_path: Path):
    """Providers at the end with no later recipients should not have collect_provider_inputs() called."""
    p0 = tmp_path / 'p0'
    p0.mkdir()
    (p0 / 'repolish.py').write_text(
        dedent(
            """
            from pydantic import BaseModel
            from repolish.loader.models import Provider

            class Ctx(BaseModel):
                pass

            class P0(Provider[Ctx, BaseModel]):
                def get_provider_name(self) -> str:
                    return 'p0'

                def create_context(self) -> Ctx:
                    return Ctx()

                def collect_provider_inputs(self, own_context, all_providers, provider_index):
                    raise RuntimeError('should not be called')
            """,
        ),
    )

    p1 = tmp_path / 'p1'
    p1.mkdir()
    (p1 / 'repolish.py').write_text('\ndef create_context():\n    return {}\n')

    # Should not raise (collect_provider_inputs of p0 must be skipped)
    create_providers([str(p0), str(p1)])


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
            create_providers(dirs)
        return

    providers = create_providers(dirs)

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
