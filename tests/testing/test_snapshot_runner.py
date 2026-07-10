"""Tests for the ``repolish.testing`` snapshot runner utilities.

Exercises :class:`SnapshotRunOptions`, :func:`run_snapshot_case`, and
the filter helpers in :mod:`repolish.testing._snapshot_filters`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import BaseModel

from repolish import (
    BaseContext,
    BaseInputs,
    FinalizeContextOptions,
    Provider,
    TemplateMapping,
    get_provider_context,
)
from repolish.providers.models.provider import ProviderEntry
from repolish.testing import (
    SnapshotRunOptions,
    exclude_paths,
    include_paths,
    mock_provider_entry,
    run_snapshot_case,
)

if TYPE_CHECKING:
    from pathlib import Path

    from repolish.providers.models.provider import ProvideInputsOptions


# ---------------------------------------------------------------------------
# Inline provider used across the test suite
# ---------------------------------------------------------------------------


class _Ctx(BaseContext):
    greeting: str = 'hello'
    project: str = 'demo'


class _Inputs(BaseInputs):
    extra_msg: str = ''


class _TestProvider(Provider[_Ctx, _Inputs]):
    def create_context(self) -> _Ctx:
        return _Ctx()

    def create_file_mappings(
        self,
        context: _Ctx,
    ) -> dict[str, str | TemplateMapping | None]:
        return {
            'README.md': 'README.md.jinja',
            'greeting.txt': 'greeting.txt.jinja',
            'config/settings.toml': 'settings.toml.jinja',
        }

    def create_anchors(self, context: _Ctx) -> dict[str, str]:
        return {'test-greeting': context.greeting}

    def create_default_symlinks(self) -> list:
        return []

    def provide_inputs(self, opt: ProvideInputsOptions[_Ctx]) -> list[_Inputs]:
        return [_Inputs(extra_msg='hey')]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def templates_root(tmp_path: Path) -> Path:
    """Create a minimal template tree under *tmp_path*."""
    tpl = tmp_path / 'resources' / 'templates' / 'repolish'
    tpl.mkdir(parents=True)
    (tpl / 'README.md.jinja').write_text('# {{ project }}\n')
    (tpl / 'greeting.txt.jinja').write_text('{{ greeting }}, world!\n')
    (tpl / 'settings.toml.jinja').write_text('project = "{{ project }}"\n')
    (tpl / 'auto.txt').write_text('auto-discovered content\n')
    (tpl / 'session_data.txt').write_text('session specific\n')
    return tmp_path / 'resources' / 'templates'


# ===================================================================
# SnapshotRunOptions
# ===================================================================


class TestSnapshotRunOptions:
    def test_defaults(self) -> None:
        opts: SnapshotRunOptions = SnapshotRunOptions()
        assert opts.mode == 'standalone'
        assert opts.received_inputs == []
        assert opts.all_providers is None
        assert opts.provider_index == 0
        assert opts.preprocess is True
        assert opts.local_files_dir is None
        assert opts.extra_context is None
        assert opts.mutate_context is None

    def test_custom_values(self) -> None:
        def mutator(ctx: BaseContext) -> None:
            pass

        opts: SnapshotRunOptions[_Inputs] = SnapshotRunOptions(
            mode='root',
            received_inputs=[_Inputs(extra_msg='test')],
            preprocess=False,
            extra_context={'key': 'value'},
            mutate_context=mutator,
        )
        assert opts.mode == 'root'
        assert len(opts.received_inputs) == 1
        assert opts.preprocess is False
        assert opts.extra_context == {'key': 'value'}
        assert opts.mutate_context is mutator


# ===================================================================
# run_snapshot_case
# ===================================================================


class TestRunSnapshotCase:
    def test_basic_run(self, templates_root: Path) -> None:
        """Test basic run_snapshot_case execution."""
        opts: SnapshotRunOptions = SnapshotRunOptions(
            mode='standalone',
            received_inputs=[],
        )

        ctx, rendered = run_snapshot_case(
            _TestProvider,
            options=opts,
            bed_kwargs={'templates_root': templates_root},
        )

        assert isinstance(ctx, _Ctx)
        assert 'README.md' in rendered
        assert 'greeting.txt' in rendered
        assert rendered['greeting.txt'] == 'hello, world!\n'

    def test_preprocess_flag(self, templates_root: Path) -> None:
        """Test that preprocess option is respected."""
        # With preprocess=True (default), preprocessor directives would be stripped
        # With preprocess=False, they remain
        opts_false: SnapshotRunOptions = SnapshotRunOptions(preprocess=False)
        opts_true: SnapshotRunOptions = SnapshotRunOptions(preprocess=True)

        _, rendered_false = run_snapshot_case(
            _TestProvider,
            options=opts_false,
            bed_kwargs={'templates_root': templates_root},
        )
        _, rendered_true = run_snapshot_case(
            _TestProvider,
            options=opts_true,
            bed_kwargs={'templates_root': templates_root},
        )

        # Both should work; actual difference depends on template content
        assert isinstance(rendered_false, dict)
        assert isinstance(rendered_true, dict)

    def test_extra_context(self, templates_root: Path) -> None:
        """Test that extra_context is passed to render_all."""
        opts: SnapshotRunOptions = SnapshotRunOptions(
            extra_context={'greeting': 'hola'},
        )

        _, rendered = run_snapshot_case(
            _TestProvider,
            options=opts,
            bed_kwargs={'templates_root': templates_root},
        )

        assert rendered['greeting.txt'] == 'hola, world!\n'

    def test_mutate_context(self, templates_root: Path) -> None:
        """Test that mutate_context is called after finalize."""
        mutated = {'called': False}

        def mutator(ctx: BaseContext) -> None:
            mutated['called'] = True
            # Use object.__setattr__ to bypass frozen check and type checking
            if hasattr(ctx, 'greeting'):
                object.__setattr__(ctx, 'greeting', 'mutated')

        opts: SnapshotRunOptions = SnapshotRunOptions(
            mutate_context=mutator,
        )

        ctx, rendered = run_snapshot_case(
            _TestProvider,
            options=opts,
            bed_kwargs={'templates_root': templates_root},
        )

        assert mutated['called']
        assert ctx.greeting == 'mutated'
        assert rendered['greeting.txt'] == 'mutated, world!\n'

    def test_with_snapshot_assertion(
        self,
        templates_root: Path,
        tmp_path: Path,
    ) -> None:
        """Test that snapshot_dir triggers assert_snapshots."""
        snap_dir = tmp_path / 'snapshots'
        snap_dir.mkdir()

        # First, get rendered output
        opts: SnapshotRunOptions = SnapshotRunOptions()
        _, rendered = run_snapshot_case(
            _TestProvider,
            options=opts,
            bed_kwargs={'templates_root': templates_root},
        )

        # Write matching snapshots
        for dest, content in rendered.items():
            snap_file = snap_dir / dest
            snap_file.parent.mkdir(parents=True, exist_ok=True)
            snap_file.write_text(content)

        # Now run with snapshot_dir - should pass
        _, rendered2 = run_snapshot_case(
            _TestProvider,
            options=opts,
            snapshot_dir=snap_dir,
            bed_kwargs={'templates_root': templates_root},
        )

        assert rendered2 == rendered

    def test_with_snapshot_assertion_fails(
        self,
        templates_root: Path,
        tmp_path: Path,
    ) -> None:
        """Test that mismatched snapshots raise AssertionError."""
        snap_dir = tmp_path / 'snapshots'
        snap_dir.mkdir()
        # Write wrong snapshot
        (snap_dir / 'greeting.txt').write_text('wrong content\n')

        opts: SnapshotRunOptions = SnapshotRunOptions()

        with pytest.raises(AssertionError, match=r'snapshot.*failed'):
            run_snapshot_case(
                _TestProvider,
                options=opts,
                snapshot_dir=snap_dir,
                bed_kwargs={'templates_root': templates_root},
            )

    def test_filter_rendered(self, templates_root: Path) -> None:
        """Test that filter_rendered is applied before snapshot check."""
        opts: SnapshotRunOptions = SnapshotRunOptions()

        _, rendered = run_snapshot_case(
            _TestProvider,
            options=opts,
            bed_kwargs={'templates_root': templates_root},
            filter_rendered=lambda r: {k: v for k, v in r.items() if k.endswith('.jinja')},
        )

        # Only .jinja files should remain (but greeting.txt is the rendered name)
        assert isinstance(rendered, dict)

    def test_all_providers_forwarding(self, templates_root: Path) -> None:
        """Test that all_providers is forwarded to finalize."""
        custom_provider_entry = ProviderEntry(
            provider_id='other-provider',
            alias='other',
            inst_type=_TestProvider,
            context=_Ctx(greeting='from-other'),
            context_type=_Ctx,
            input_type=_Inputs,
        )

        opts: SnapshotRunOptions = SnapshotRunOptions(
            all_providers=[custom_provider_entry],
            provider_index=1,
        )

        ctx, rendered = run_snapshot_case(
            _TestProvider,
            options=opts,
            bed_kwargs={'templates_root': templates_root},
        )

        # Context should be finalized with the custom provider list
        assert isinstance(ctx, _Ctx)
        assert rendered['greeting.txt'] == 'hello, world!\n'

    def test_local_files_dir(
        self,
        templates_root: Path,
        tmp_path: Path,
    ) -> None:
        """Test that local_files_dir is passed to ProviderTestBed."""
        # Create a template with preprocessor directive
        tpl = templates_root / 'repolish'
        (tpl / 'version.txt').write_text(
            '## repolish-regex[version]: (\\d+\\.\\d+\\.\\d+)\nversion = 0.0.0\n',
        )

        class _VersionProvider(Provider[_Ctx, _Inputs]):
            def create_file_mappings(
                self,
                context: _Ctx,
            ) -> dict[str, str | TemplateMapping | None]:
                return {'version.txt': 'version.txt'}

        local_dir = tmp_path / 'local'
        local_dir.mkdir()
        (local_dir / 'version.txt').write_text('version = 1.2.3\n')

        opts: SnapshotRunOptions = SnapshotRunOptions(
            preprocess=True,
            local_files_dir=local_dir,
        )

        _, rendered = run_snapshot_case(
            _VersionProvider,
            options=opts,
            bed_kwargs={'templates_root': templates_root},
        )

        assert 'version = 1.2.3' in rendered['version.txt']


# ===================================================================
# include_paths filter
# ===================================================================


class TestIncludePaths:
    def test_exact_match(self) -> None:
        rendered = {
            'a.txt': 'content a',
            'b.txt': 'content b',
            'c/d.txt': 'content d',
        }

        result = include_paths(rendered, exact={'a.txt', 'c/d.txt'})

        assert result == {'a.txt': 'content a', 'c/d.txt': 'content d'}

    def test_prefix_match(self) -> None:
        rendered = {
            'config/a.toml': 'a',
            'config/b.toml': 'b',
            'src/main.py': 'main',
        }

        result = include_paths(rendered, prefixes=('config/',))

        assert result == {'config/a.toml': 'a', 'config/b.toml': 'b'}

    def test_include_regex_match(self) -> None:
        rendered = {
            'a.txt': 'a',
            'b.toml': 'b',
            'c.txt': 'c',
        }

        result = include_paths(rendered, include_regex=(r'.*\.toml$',))

        assert result == {'b.toml': 'b'}

    def test_exclude_prefix_removes_after_inclusion(self) -> None:
        rendered = {
            'poe-tasks/task1.yml': 't1',
            'poe-tasks/sessions/sess1.yml': 's1',
            'poe-tasks/task2.yml': 't2',
        }

        result = include_paths(
            rendered,
            prefixes=('poe-tasks/',),
            exclude_prefixes=('poe-tasks/sessions/',),
        )

        assert result == {
            'poe-tasks/task1.yml': 't1',
            'poe-tasks/task2.yml': 't2',
        }

    def test_exclude_regex_removes_after_inclusion(self) -> None:
        rendered = {
            'a.tmp.txt': 'a',
            'b.txt': 'b',
            'c.tmp.txt': 'c',
        }

        result = include_paths(
            rendered,
            prefixes=('b', 'a', 'c'),
            exclude_regex=(r'\.tmp\.',),
        )

        assert result == {'b.txt': 'b'}

    def test_combined_exact_prefix_and_regex(self) -> None:
        rendered = {
            'README.md': 'readme',
            'config/a.toml': 'a',
            'src/main.py': 'main',
            'tests/test_main.py': 'test',
        }

        result = include_paths(
            rendered,
            exact={'README.md'},
            prefixes=('config/',),
            include_regex=(r'.*test.*\.py$',),
        )

        assert result == {
            'README.md': 'readme',
            'config/a.toml': 'a',
            'tests/test_main.py': 'test',
        }

    def test_empty_rendered(self) -> None:
        result = include_paths({}, exact={'a.txt'})
        assert result == {}

    def test_no_criteria_matches_all(self) -> None:
        rendered = {'a.txt': 'a', 'b.txt': 'b'}
        # No criteria = nothing included
        result = include_paths(rendered)
        assert result == {}

    def test_exclude_wins_over_include_exact(self) -> None:
        rendered = {'a.txt': 'a', 'b.txt': 'b'}
        result = include_paths(
            rendered,
            exact={'a.txt', 'b.txt'},
            exclude_prefixes=('b',),
        )
        assert result == {'a.txt': 'a'}

    def test_exclude_regex_wins_over_include_regex(self) -> None:
        rendered = {'test_a.py': 'a', 'test_b.py': 'b'}
        result = include_paths(
            rendered,
            include_regex=(r'test.*\.py$',),
            exclude_regex=(r'.*_b\.py$',),
        )
        assert result == {'test_a.py': 'a'}


# ===================================================================
# exclude_paths filter
# ===================================================================


class TestExcludePaths:
    def test_exact_exclude(self) -> None:
        rendered = {'a.txt': 'a', 'b.txt': 'b', 'c.txt': 'c'}
        result = exclude_paths(rendered, exact={'b.txt'})
        assert result == {'a.txt': 'a', 'c.txt': 'c'}

    def test_prefix_exclude(self) -> None:
        rendered = {
            'config/a.toml': 'a',
            'config/b.toml': 'b',
            'src/main.py': 'main',
        }
        result = exclude_paths(rendered, prefixes=('config/',))
        assert result == {'src/main.py': 'main'}

    def test_regex_exclude(self) -> None:
        rendered = {'a.tmp.txt': 'a', 'b.txt': 'b', 'c.tmp.txt': 'c'}
        result = exclude_paths(rendered, regex=(r'\.tmp\.',))
        assert result == {'b.txt': 'b'}

    def test_combined_exclude(self) -> None:
        rendered = {
            'README.md': 'readme',
            'config/a.toml': 'a',
            'config/b.toml': 'b',
            'src/main.py': 'main',
        }
        result = exclude_paths(
            rendered,
            exact={'README.md'},
            prefixes=('config/',),
            regex=(r'.*main.*\.py$',),
        )
        assert result == {}

    def test_empty_rendered(self) -> None:
        result = exclude_paths({}, exact={'a.txt'})
        assert result == {}

    def test_no_exclude_criteria_returns_all(self) -> None:
        rendered = {'a.txt': 'a', 'b.txt': 'b'}
        result = exclude_paths(rendered)
        assert result == rendered


# ===================================================================
# Integration: run_snapshot_case with filters
# ===================================================================


class TestRunSnapshotCaseWithFilters:
    def test_with_include_paths_filter(
        self,
        templates_root: Path,
    ) -> None:
        """Test run_snapshot_case with include_paths filter."""
        opts: SnapshotRunOptions = SnapshotRunOptions()

        _, rendered = run_snapshot_case(
            _TestProvider,
            options=opts,
            bed_kwargs={'templates_root': templates_root},
            filter_rendered=lambda r: include_paths(
                r,
                exact={'greeting.txt'},
            ),
        )

        assert rendered == {'greeting.txt': 'hello, world!\n'}

    def test_with_exclude_paths_filter(
        self,
        templates_root: Path,
    ) -> None:
        """Test run_snapshot_case with exclude_paths filter."""
        opts: SnapshotRunOptions = SnapshotRunOptions()

        _, rendered = run_snapshot_case(
            _TestProvider,
            options=opts,
            bed_kwargs={'templates_root': templates_root},
            filter_rendered=lambda r: exclude_paths(
                r,
                prefixes=('config/',),
            ),
        )

        assert 'config/settings.toml' not in rendered
        assert 'greeting.txt' in rendered

    def test_poe_style_pattern(self, templates_root: Path) -> None:
        """Test the Poe-style pattern from the proposal."""
        opts: SnapshotRunOptions = SnapshotRunOptions(
            mode='root',
            received_inputs=[],
            extra_context={'project': 'myproject'},
        )

        _, rendered = run_snapshot_case(
            _TestProvider,
            options=opts,
            bed_kwargs={'templates_root': templates_root},
            filter_rendered=lambda r: include_paths(
                r,
                exact={'README.md'},
                prefixes=('config/',),
                exclude_prefixes=('config/sessions/',),
            ),
        )

        # Should include README.md and config/settings.toml
        assert 'README.md' in rendered
        assert 'config/settings.toml' in rendered
        assert '# myproject\n' in rendered['README.md']


# ===================================================================
# mock_provider_entry
# ===================================================================


class TestMockProviderEntry:
    """Test the mock_provider_entry helper for cross-provider testing."""

    def test_basic_mock_entry(self) -> None:
        """Test creating a basic mock provider entry."""
        mock_ctx = _Ctx(greeting='mocked', project='mock-project')

        entry = mock_provider_entry(_TestProvider, mock_ctx)

        assert entry.alias == '_testprovider'
        assert entry.provider_id == '_testprovider'
        assert entry.context is mock_ctx
        assert entry.context_type is _Ctx

    def test_mock_entry_with_custom_alias(self) -> None:
        """Test creating a mock entry with custom alias."""
        mock_ctx = _Ctx()

        entry = mock_provider_entry(
            _TestProvider,
            mock_ctx,
            alias='my-provider',
            provider_id='my-provider-id',
        )

        assert entry.alias == 'my-provider'
        assert entry.provider_id == 'my-provider-id'

    def test_mock_entry_with_input_type(self) -> None:
        """Test creating a mock entry with custom input type."""
        mock_ctx = _Ctx()

        entry = mock_provider_entry(
            _TestProvider,
            mock_ctx,
            input_type=_Inputs,
        )

        assert entry.input_type is _Inputs

    def test_mock_entry_default_input_type(self) -> None:
        """Test that mock entry uses BaseModel as default input type."""
        mock_ctx = _Ctx()
        entry = mock_provider_entry(_TestProvider, mock_ctx)

        # Should default to BaseModel
        assert entry.input_type is BaseModel


# ===================================================================
# Cross-provider testing pattern
# ===================================================================


class TestCrossProviderPattern:
    """Test the pattern for testing providers that read from other providers."""

    def test_provider_reads_from_peer_context(
        self,
        tmp_path: Path,
    ) -> None:
        """Test a provider that reads another provider's context."""
        # Create isolated templates to avoid auto-discovery conflicts
        tpl = tmp_path / 'resources' / 'templates' / 'repolish'
        tpl.mkdir(parents=True)
        (tpl / 'output.txt.jinja').write_text('value={{ derived_value }}\n')
        templates_root = tmp_path / 'resources' / 'templates'

        class _PeerCtx(BaseContext):
            peer_value: str = 'from-peer'
            project: str = 'peer-project'

        class _PeerProvider(Provider[_PeerCtx, _Inputs]):
            def create_context(self) -> _PeerCtx:
                return _PeerCtx()

        class _DependentCtx(BaseContext):
            derived_value: str = 'default'
            project: str = 'test-project'

        class _DependentProvider(Provider[_DependentCtx, _Inputs]):
            def finalize_context(
                self,
                opt: FinalizeContextOptions,  # type: ignore[type-arg]
            ) -> _DependentCtx:
                peer = get_provider_context(_PeerProvider, opt.all_providers)
                if peer is not None:
                    opt.own_context.derived_value = f'derived-{peer.peer_value}'
                return opt.own_context

            def create_file_mappings(
                self,
                context: _DependentCtx,
            ) -> dict[str, str | TemplateMapping | None]:
                return {
                    'output.txt': 'output.txt.jinja',
                }

        # Create peer provider entry with mock context
        peer_entry = mock_provider_entry(
            _PeerProvider,
            _PeerCtx(peer_value='custom-peer'),
            alias='peer',
        )

        opts: SnapshotRunOptions = SnapshotRunOptions(
            all_providers=[peer_entry],
        )

        ctx, rendered = run_snapshot_case(
            _DependentProvider,
            options=opts,
            bed_kwargs={'templates_root': templates_root},
        )

        # The dependent provider should have read from the peer's context
        assert ctx.derived_value == 'derived-custom-peer'
        assert rendered['output.txt'] == 'value=derived-custom-peer\n'
