"""Tests for the ``repolish.testing`` provider-author test utilities.

Exercises :class:`ProviderTestBed`, :func:`make_context`, and
:func:`assert_snapshots` against a small inline provider with templates
on disk.  This validates the framework itself while demonstrating the
intended usage.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest import mock

import pytest

from repolish import BaseContext, BaseInputs, Provider, TemplateMapping
from repolish.testing import ProviderTestBed, assert_snapshots, make_context

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
            'README.md': 'README.md',
            'greeting.txt': 'greeting.txt.jinja',
            'deleted.txt': None,
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
    (tpl / 'README.md').write_text('# {{ project }}\n')
    (tpl / 'greeting.txt.jinja').write_text('{{ greeting }}, world!\n')
    (tpl / 'auto.txt').write_text('auto-discovered content\n')
    return tmp_path / 'resources' / 'templates'


# ===================================================================
# make_context
# ===================================================================


class TestMakeContext:
    def test_defaults(self) -> None:
        ctx = make_context()
        assert ctx.workspace.mode == 'standalone'
        assert ctx.provider.alias == 'test-provider'
        assert ctx.provider.version == '0.1.0'
        assert ctx.repo.owner == 'test-owner'
        assert ctx.repo.name == 'test-repo'

    def test_custom_values(self) -> None:
        ctx = make_context(
            mode='root',
            alias='my-prov',
            version='2.0.0',
            repo_owner='acme',
            repo_name='widgets',
        )
        assert ctx.workspace.mode == 'root'
        assert ctx.provider.alias == 'my-prov'
        assert ctx.provider.version == '2.0.0'
        assert ctx.repo.owner == 'acme'
        assert ctx.repo.name == 'widgets'

    def test_session_mode_matches_workspace_mode(self) -> None:
        for mode in ('root', 'member', 'standalone'):
            ctx = make_context(mode=mode)  # type: ignore[arg-type]
            assert ctx.provider.session.mode == mode


# ===================================================================
# assert_snapshots
# ===================================================================


class TestAssertSnapshots:
    def test_matching_snapshots_pass(self, tmp_path: Path) -> None:
        snap_dir = tmp_path / 'snapshots'
        snap_dir.mkdir()
        (snap_dir / 'a.txt').write_text('hello\n')
        (snap_dir / 'b.txt').write_text('world\n')

        rendered = {'a.txt': 'hello\n', 'b.txt': 'world\n'}
        assert_snapshots(rendered, snap_dir)

    def test_mismatch_raises(self, tmp_path: Path) -> None:
        snap_dir = tmp_path / 'snapshots'
        snap_dir.mkdir()
        (snap_dir / 'a.txt').write_text('expected\n')

        with pytest.raises(AssertionError, match=r'1 snapshot.*failed'):
            assert_snapshots({'a.txt': 'actual\n'}, snap_dir)

    def test_missing_snapshot_raises(self, tmp_path: Path) -> None:
        snap_dir = tmp_path / 'snapshots'
        snap_dir.mkdir()

        with pytest.raises(AssertionError, match='missing snapshot'):
            assert_snapshots({'new.txt': 'content\n'}, snap_dir)

    def test_nested_snapshot_path(self, tmp_path: Path) -> None:
        snap_dir = tmp_path / 'snapshots'
        nested = snap_dir / 'sub' / 'dir'
        nested.mkdir(parents=True)
        (nested / 'deep.txt').write_text('ok\n')

        assert_snapshots({'sub/dir/deep.txt': 'ok\n'}, snap_dir)

    def test_empty_rendered_passes(self, tmp_path: Path) -> None:
        snap_dir = tmp_path / 'snapshots'
        snap_dir.mkdir()
        assert_snapshots({}, snap_dir)

    def test_trailing_whitespace_diff_fallback(
        self,
        tmp_path: Path,
    ) -> None:
        snap_dir = tmp_path / 'snapshots'
        snap_dir.mkdir()
        (snap_dir / 'ws.txt').write_text('hello')

        # Force unified_diff to return nothing so the fallback message fires
        with (
            mock.patch('difflib.unified_diff', return_value=iter([])),
            pytest.raises(
                AssertionError,
                match='contents differ',
            ),
        ):
            assert_snapshots({'ws.txt': 'hello '}, snap_dir)


# ===================================================================
# ProviderTestBed - lifecycle hooks
# ===================================================================


class TestProviderTestBedHooks:
    def test_create_context_auto(self, templates_root: Path) -> None:
        bed = ProviderTestBed(
            provider_class=_TestProvider,
            templates_root=templates_root,
        )
        ctx = bed.resolved_context
        assert isinstance(ctx, _Ctx)
        assert ctx.greeting == 'hello'

    def test_create_context_explicit(self, templates_root: Path) -> None:
        custom = _Ctx(greeting='hi', project='custom')
        bed = ProviderTestBed(
            provider_class=_TestProvider,
            context=custom,
            templates_root=templates_root,
        )
        assert bed.resolved_context.greeting == 'hi'
        assert bed.resolved_context.project == 'custom'

    def test_file_mappings(self, templates_root: Path) -> None:
        bed = ProviderTestBed(
            provider_class=_TestProvider,
            templates_root=templates_root,
        )
        fm = bed.file_mappings()
        assert 'README.md' in fm
        assert 'greeting.txt' in fm
        assert fm['deleted.txt'] is None

    def test_anchors(self, templates_root: Path) -> None:
        bed = ProviderTestBed(
            provider_class=_TestProvider,
            templates_root=templates_root,
        )
        anchors = bed.anchors()
        assert anchors == {'test-greeting': 'hello'}

    def test_symlinks(self, templates_root: Path) -> None:
        bed = ProviderTestBed(
            provider_class=_TestProvider,
            templates_root=templates_root,
        )
        assert bed.symlinks() == []

    def test_provide_inputs(self, templates_root: Path) -> None:
        bed = ProviderTestBed(
            provider_class=_TestProvider,
            templates_root=templates_root,
        )
        inputs = bed.provide_inputs()
        assert len(inputs) == 1
        assert isinstance(inputs[0], _Inputs)
        assert inputs[0].extra_msg == 'hey'

    def test_finalize(self, templates_root: Path) -> None:
        bed = ProviderTestBed(
            provider_class=_TestProvider,
            templates_root=templates_root,
        )
        result = bed.finalize(received_inputs=[])
        assert isinstance(result, _Ctx)
        assert bed.resolved_context is result


# ===================================================================
# ProviderTestBed - template rendering
# ===================================================================


class TestProviderTestBedRender:
    def test_render_jinja(self, templates_root: Path) -> None:
        bed = ProviderTestBed(
            provider_class=_TestProvider,
            templates_root=templates_root,
        )
        out = bed.render('greeting.txt.jinja')
        assert out == 'hello, world!\n'

    def test_render_static(self, templates_root: Path) -> None:
        bed = ProviderTestBed(
            provider_class=_TestProvider,
            templates_root=templates_root,
        )
        out = bed.render('README.md')
        # render() processes all files through Jinja regardless of extension
        assert out == '# demo\n'

    def test_render_missing_raises(self, templates_root: Path) -> None:
        bed = ProviderTestBed(
            provider_class=_TestProvider,
            templates_root=templates_root,
        )
        with pytest.raises(FileNotFoundError, match='template not found'):
            bed.render('nonexistent.txt')

    def test_render_with_extra_context(self, templates_root: Path) -> None:
        bed = ProviderTestBed(
            provider_class=_TestProvider,
            templates_root=templates_root,
        )
        out = bed.render(
            'greeting.txt.jinja',
            extra_context={'greeting': 'hola'},
        )
        assert out == 'hola, world!\n'

    def test_render_all_includes_mapped_and_auto(
        self,
        templates_root: Path,
    ) -> None:
        bed = ProviderTestBed(
            provider_class=_TestProvider,
            templates_root=templates_root,
        )
        rendered = bed.render_all()
        # Mapped templates
        assert 'README.md' in rendered
        assert 'greeting.txt' in rendered
        # Auto-discovered (non-prefixed, not already mapped)
        assert 'auto.txt' in rendered
        assert rendered['auto.txt'] == 'auto-discovered content\n'
        # Deleted mapping should be absent
        assert 'deleted.txt' not in rendered

    def test_render_all_jinja_rendered(self, templates_root: Path) -> None:
        bed = ProviderTestBed(
            provider_class=_TestProvider,
            templates_root=templates_root,
        )
        rendered = bed.render_all()
        assert rendered['greeting.txt'] == 'hello, world!\n'

    def test_render_all_with_extra_context(
        self,
        templates_root: Path,
    ) -> None:
        bed = ProviderTestBed(
            provider_class=_TestProvider,
            templates_root=templates_root,
        )
        rendered = bed.render_all(extra_context={'greeting': 'hola'})
        assert rendered['greeting.txt'] == 'hola, world!\n'

    def test_render_all_with_snapshots(
        self,
        templates_root: Path,
        tmp_path: Path,
    ) -> None:
        bed = ProviderTestBed(
            provider_class=_TestProvider,
            templates_root=templates_root,
        )
        rendered = bed.render_all()

        # Write snapshot files that match the rendered output
        snap_dir = tmp_path / 'snapshots'
        for dest, content in rendered.items():
            snap_file = snap_dir / dest
            snap_file.parent.mkdir(parents=True, exist_ok=True)
            snap_file.write_text(content)

        assert_snapshots(rendered, snap_dir)


# ===================================================================
# ProviderTestBed - mode dispatch
# ===================================================================


@dataclass
class _ModeCase:
    name: str
    mode: str
    expected_anchor_key: str


class TestProviderTestBedModeDispatch:
    """Verify that ProviderTestBed respects mode-handler dispatch."""

    def test_mode_injected_into_repolish_context(
        self,
        templates_root: Path,
    ) -> None:
        bed = ProviderTestBed(
            provider_class=_TestProvider,
            mode='root',
            templates_root=templates_root,
        )
        assert bed.resolved_context.repolish.workspace.mode == 'root'

    def test_standalone_mode_default(self, templates_root: Path) -> None:
        bed = ProviderTestBed(
            provider_class=_TestProvider,
            templates_root=templates_root,
        )
        assert bed.resolved_context.repolish.workspace.mode == 'standalone'

    def test_alias_and_version_injected(self, templates_root: Path) -> None:
        bed = ProviderTestBed(
            provider_class=_TestProvider,
            alias='my-alias',
            version='3.2.1',
            templates_root=templates_root,
        )
        assert bed.resolved_context.repolish.provider.alias == 'my-alias'
        assert bed.resolved_context.repolish.provider.version == '3.2.1'


# ===================================================================
# ProviderTestBed - _repolish. prefix exclusion
# ===================================================================


class TestAutoDiscoveryExcludesRepolishPrefix:
    def test_repolish_prefixed_not_auto_discovered(
        self,
        tmp_path: Path,
    ) -> None:
        tpl = tmp_path / 'resources' / 'templates' / 'repolish'
        tpl.mkdir(parents=True)
        (tpl / 'normal.txt').write_text('visible\n')
        (tpl / '_repolish.hidden.txt').write_text('hidden\n')
        # Add a subdirectory with a file to exercise the is_dir() skip
        sub = tpl / 'subdir'
        sub.mkdir()
        (sub / 'nested.txt').write_text('nested\n')
        templates_root = tmp_path / 'resources' / 'templates'

        class _MinimalProvider(Provider[_Ctx, _Inputs]):
            def create_file_mappings(
                self,
                context: _Ctx,
            ) -> dict[str, str | TemplateMapping | None]:
                return {}

        bed = ProviderTestBed(
            provider_class=_MinimalProvider,
            templates_root=templates_root,
        )
        rendered = bed.render_all()
        assert 'normal.txt' in rendered
        assert '_repolish.hidden.txt' not in rendered
        assert 'subdir/nested.txt' in rendered

    def test_repolish_prefixed_included_when_explicitly_mapped(
        self,
        tmp_path: Path,
    ) -> None:
        tpl = tmp_path / 'resources' / 'templates' / 'repolish'
        tpl.mkdir(parents=True)
        (tpl / '_repolish.mapped.txt').write_text('mapped content\n')
        templates_root = tmp_path / 'resources' / 'templates'

        class _MappingProvider(Provider[_Ctx, _Inputs]):
            def create_file_mappings(
                self,
                context: _Ctx,
            ) -> dict[str, str | TemplateMapping | None]:
                return {'output.txt': '_repolish.mapped.txt'}

        bed = ProviderTestBed(
            provider_class=_MappingProvider,
            templates_root=templates_root,
        )
        rendered = bed.render_all()
        assert rendered['output.txt'] == 'mapped content\n'


# ===================================================================
# ProviderTestBed - promote_file_mappings
# ===================================================================


class TestPromoteFileMappings:
    def test_promote_file_mappings_default_empty(
        self,
        templates_root: Path,
    ) -> None:
        bed = ProviderTestBed(
            provider_class=_TestProvider,
            templates_root=templates_root,
        )
        assert bed.promote_file_mappings() == {}


# ===================================================================
# ProviderTestBed - _locate_templates_root
# ===================================================================


class TestLocateTemplatesRoot:
    def test_auto_detect_templates_root(self, tmp_path: Path) -> None:
        # Create a provider module on disk with resources/templates alongside
        pkg = tmp_path / 'mypkg' / 'repolish'
        pkg.mkdir(parents=True)
        tpl = tmp_path / 'mypkg' / 'resources' / 'templates' / 'repolish'
        tpl.mkdir(parents=True)
        (tpl / 'hello.txt').write_text('hi\n')

        # Write a provider module
        provider_src = (
            'from repolish import BaseContext, Provider\n'
            'from pydantic import BaseModel\n'
            'class _AutoCtx(BaseContext):\n'
            '    pass\n'
            'class _AutoProvider(Provider[_AutoCtx, BaseModel]):\n'
            '    pass\n'
        )
        (pkg / '__init__.py').write_text('')
        (pkg / 'provider.py').write_text(provider_src)

        sys.path.insert(0, str(tmp_path))
        try:
            mod = __import__(
                'mypkg.repolish.provider',
                fromlist=['_AutoProvider'],
            )
            bed = ProviderTestBed(provider_class=mod._AutoProvider)
            assert bed._templates_root == tpl.parent
            rendered = bed.render('hello.txt')
            assert rendered == 'hi\n'
        finally:
            sys.path.remove(str(tmp_path))
            sys.modules.pop('mypkg', None)
            sys.modules.pop('mypkg.repolish', None)
            sys.modules.pop('mypkg.repolish.provider', None)

    def test_locate_raises_when_no_templates(self, tmp_path: Path) -> None:
        # Create a provider module with no resources/templates
        pkg = tmp_path / 'nopkg' / 'repolish'
        pkg.mkdir(parents=True)
        (pkg / '__init__.py').write_text('')
        provider_src = (
            'from repolish import BaseContext, Provider\n'
            'from pydantic import BaseModel\n'
            'class _NoTplProvider(Provider[BaseContext, BaseModel]):\n'
            '    pass\n'
        )
        (pkg / 'provider.py').write_text(provider_src)
        # Add pyproject.toml to stop the walk
        (tmp_path / 'nopkg' / 'pyproject.toml').write_text('')

        sys.path.insert(0, str(tmp_path))
        try:
            mod = __import__(
                'nopkg.repolish.provider',
                fromlist=['_NoTplProvider'],
            )
            with pytest.raises(
                RuntimeError,
                match='cannot find resources/templates',
            ):
                ProviderTestBed(provider_class=mod._NoTplProvider)
        finally:
            sys.path.remove(str(tmp_path))
            sys.modules.pop('nopkg', None)
            sys.modules.pop('nopkg.repolish', None)
            sys.modules.pop('nopkg.repolish.provider', None)


# ===================================================================
# Edge cases: binary templates, missing template dir, TemplateMapping
# ===================================================================


class TestEdgeCases:
    def test_render_all_binary_file(self, tmp_path: Path) -> None:
        tpl = tmp_path / 'resources' / 'templates' / 'repolish'
        tpl.mkdir(parents=True)
        # Write a non-UTF-8 file to hit the UnicodeDecodeError path
        (tpl / 'binary.dat').write_bytes(b'\x80\x81\x82\xff')
        templates_root = tmp_path / 'resources' / 'templates'

        class _EmptyProvider(Provider[_Ctx, _Inputs]):
            def create_file_mappings(
                self,
                context: _Ctx,
            ) -> dict[str, str | TemplateMapping | None]:
                return {}

        bed = ProviderTestBed(
            provider_class=_EmptyProvider,
            templates_root=templates_root,
        )
        rendered = bed.render_all()
        assert 'binary.dat' in rendered

    def test_render_all_no_template_dir(self, tmp_path: Path) -> None:
        # templates_root exists but repolish/ subdir does not
        templates_root = tmp_path / 'resources' / 'templates'
        templates_root.mkdir(parents=True)

        class _EmptyProvider(Provider[_Ctx, _Inputs]):
            def create_file_mappings(
                self,
                context: _Ctx,
            ) -> dict[str, str | TemplateMapping | None]:
                return {}

        bed = ProviderTestBed(
            provider_class=_EmptyProvider,
            templates_root=templates_root,
        )
        rendered = bed.render_all()
        assert rendered == {}

    def test_render_all_template_mapping_with_none_source(
        self,
        tmp_path: Path,
    ) -> None:
        tpl = tmp_path / 'resources' / 'templates' / 'repolish'
        tpl.mkdir(parents=True)
        templates_root = tmp_path / 'resources' / 'templates'

        class _TMNoneProvider(Provider[_Ctx, _Inputs]):
            def create_file_mappings(
                self,
                context: _Ctx,
            ) -> dict[str, str | TemplateMapping | None]:
                return {'out.txt': TemplateMapping(None)}

        bed = ProviderTestBed(
            provider_class=_TMNoneProvider,
            templates_root=templates_root,
        )
        rendered = bed.render_all()
        assert 'out.txt' not in rendered

    def test_render_all_template_mapping_with_source(
        self,
        tmp_path: Path,
    ) -> None:
        tpl = tmp_path / 'resources' / 'templates' / 'repolish'
        tpl.mkdir(parents=True)
        (tpl / '_repolish.src.txt').write_text('from mapping\n')
        templates_root = tmp_path / 'resources' / 'templates'

        class _TMMappedProvider(Provider[_Ctx, _Inputs]):
            def create_file_mappings(
                self,
                context: _Ctx,
            ) -> dict[str, str | TemplateMapping | None]:
                return {'dest.txt': TemplateMapping('_repolish.src.txt')}

        bed = ProviderTestBed(
            provider_class=_TMMappedProvider,
            templates_root=templates_root,
        )
        rendered = bed.render_all()
        assert rendered['dest.txt'] == 'from mapping\n'
