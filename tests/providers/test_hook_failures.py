"""Uniform hook-failure handling: record, skip, and exit 1.

A provider or facet hook that raises is never fatal: the pipeline records
a `HookFailure`, skips that hook, and keeps going. These tests pin the
model end to end: the failures ride the `SessionBundle`, the debug
reports land in `.repolish/_/hook-failures/`, and both apply and check
exit 1 while the healthy work still happens.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import sys
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, Any

from repolish.providers import create_providers
from repolish.providers.models import (
    HookFailureCollector,
    SessionBundle,
)
from repolish.providers.models.hooks import traceback_lines
from repolish.testing import apply_provider

if TYPE_CHECKING:
    from types import ModuleType

    from repolish.providers.models import Provider
    from repolish.testing import ApplyResult

_counter = itertools.count()


def _raise(exc: Exception) -> None:
    """Raise from outside the try block so tests read as users would write them."""
    raise exc


def _load_module(path: Path) -> ModuleType:
    name = f'_hook_failure_provider_{next(_counter)}'
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_provider(
    tmp_path: Path,
    src: str,
    templates: dict[str, str],
) -> tuple[ModuleType, Path]:
    provider_root = tmp_path / 'pkg' / 'resources' / 'templates'
    (provider_root / 'repolish').mkdir(parents=True)
    (provider_root / 'repolish.py').write_text(
        textwrap.dedent(src),
        encoding='utf-8',
    )
    for name, content in templates.items():
        (provider_root / 'repolish' / name).write_text(
            textwrap.dedent(content),
            encoding='utf-8',
        )
    return _load_module(provider_root / 'repolish.py'), provider_root


def _apply(
    provider_class: type[Provider[Any, Any]],
    tmp_path: Path,
    *,
    alias: str,
    check_only: bool = False,
) -> ApplyResult:
    project = tmp_path / 'project'
    project.mkdir()
    return apply_provider(
        provider_class,
        project,
        alias=alias,
        check_only=check_only,
    )


# ---------------------------------------------------------------------------
# The record itself
# ---------------------------------------------------------------------------


def test_collector_records_traceback_and_alias_fallback() -> None:
    """record() captures the traceback and falls back to provider_id for alias."""
    collector = HookFailureCollector()
    try:
        _raise(RuntimeError('boom'))
    except RuntimeError as exc:
        collector.record(provider_id='p', hook='create_context', exc=exc)
    (failure,) = collector.failures
    assert failure.alias == 'p'
    assert failure.hook == 'create_context'
    assert failure.error == 'boom'
    assert 'RuntimeError: boom' in ''.join(failure.traceback)
    assert failure.report_path is None


def test_traceback_lines_matches_format_exception() -> None:
    try:
        _raise(ValueError('nope'))
    except ValueError as exc:
        lines = traceback_lines(exc)
    assert ''.join(lines).strip().endswith('ValueError: nope')


# ---------------------------------------------------------------------------
# Provider contribution hooks: record and skip, one per hook
# ---------------------------------------------------------------------------


_ALL_HOOKS_BROKEN_PROVIDER = """\
    from repolish import BaseContext, BaseInputs, Provider

    class Ctx(BaseContext):
        pass

    class P(Provider[Ctx, BaseInputs]):
        def create_context(self):
            return Ctx()

        def create_file_mappings(self, context):
            raise RuntimeError('mappings boom')

        def create_file_validators(self, context):
            raise RuntimeError('validators boom')

        def create_file_insertions(self, context):
            raise RuntimeError('insertions boom')

        def create_fast_lanes(self, context):
            raise RuntimeError('fast lanes boom')

        def promote_file_mappings(self, context):
            raise RuntimeError('promote boom')
    """


def test_broken_contribution_hooks_are_recorded_and_skipped(
    tmp_path: Path,
) -> None:
    _, provider_root = _write_provider(tmp_path, _ALL_HOOKS_BROKEN_PROVIDER, {})
    providers = create_providers([str(provider_root)])
    hooks = sorted(f.hook for f in providers.hook_failures)
    assert hooks == [
        'create_fast_lanes',
        'create_file_insertions',
        'create_file_mappings',
        'create_file_validators',
        'promote_file_mappings',
    ]
    # Every broken hook's contribution is simply absent: the run continues
    # with a provider that contributes nothing beyond its context.
    assert providers.file_mappings == {}
    assert providers.file_validators == {}
    assert providers.file_insertions == {}
    assert providers.fast_lanes == {}


_FACET_INPUTS_BROKEN_PROVIDER = """\
    from repolish import (
        BaseContext,
        BaseInputs,
        FacetInputsOptions,
        FacetSpec,
        Provider,
        ProviderFacet,
    )

    class Ctx(BaseContext):
        pass

    class BrokenFacet(ProviderFacet[Ctx, BaseInputs]):
        name = 'broken'

        def provide_inputs(self, opt: FacetInputsOptions[Ctx]):
            raise RuntimeError('facet inputs boom')

        def create_spec(self, opt):
            return FacetSpec()

    class P(Provider[Ctx, BaseInputs]):
        facets = [BrokenFacet]

        def create_context(self):
            return Ctx()
    """


def test_broken_facet_provide_inputs_records_and_emits_nothing(
    tmp_path: Path,
) -> None:
    mod, _ = _write_provider(tmp_path, _FACET_INPUTS_BROKEN_PROVIDER, {})
    result = _apply(mod.P, tmp_path, alias='broken-facet')
    assert result.exit_code == 1
    (failure,) = result.session.providers.hook_failures
    assert failure.hook == 'provide_inputs'
    assert failure.facet_name == 'broken'
    assert result.emitted_inputs == []


# ---------------------------------------------------------------------------
# End to end: the summary's data path, apply and check
# ---------------------------------------------------------------------------

_FACET_SPEC_BROKEN_PROVIDER = """\
    from repolish import (
        BaseContext,
        BaseInputs,
        FacetSpec,
        FacetSpecOptions,
        Provider,
        ProviderFacet,
        TemplateMapping,
    )

    class Ctx(BaseContext):
        pass

    class BrokenFacet(ProviderFacet[Ctx, BaseInputs]):
        name = 'broken'

        def create_spec(self, opt: FacetSpecOptions[Ctx]):
            raise RuntimeError('spec boom')

    class P(Provider[Ctx, BaseInputs]):
        facets = [BrokenFacet]

        def create_context(self):
            return Ctx()

        def create_file_mappings(self, context):
            return {'GOOD.md': TemplateMapping(source_template='GOOD.md.jinja')}
    """

_TEMPLATES = {'GOOD.md.jinja': 'good\n'}


def _apply_broken_facet(
    tmp_path: Path,
    *,
    check_only: bool = False,
) -> ApplyResult:
    mod, _ = _write_provider(tmp_path, _FACET_SPEC_BROKEN_PROVIDER, _TEMPLATES)
    return _apply(mod.P, tmp_path, alias='demo', check_only=check_only)


def test_broken_facet_spec_exits_one_but_applies_the_rest(
    tmp_path: Path,
) -> None:
    result = _apply_broken_facet(tmp_path)
    assert result.exit_code == 1
    # The healthy mapping was still applied; the facet's file never existed.
    assert result.apply_result == {'GOOD.md': 'written'}
    (failure,) = result.session.providers.hook_failures
    assert failure.hook == 'create_spec'
    assert failure.facet_name == 'broken'
    assert failure.error == 'spec boom'
    # The debug report was written and the record points at it.
    assert failure.report_path is not None
    report = Path(result.project_dir / failure.report_path)
    assert report.is_file()
    payload: dict = json.loads(report.read_text(encoding='utf-8'))
    assert payload['hook'] == 'create_spec'
    assert 'RuntimeError: spec boom' in ''.join(payload['traceback'])
    assert str(report).startswith(
        str(result.project_dir / '.repolish' / '_' / 'hook-failures'),
    )


def test_broken_facet_spec_exits_one_in_check_mode(tmp_path: Path) -> None:
    result = _apply_broken_facet(tmp_path, check_only=True)
    assert result.exit_code == 1


_FINALIZE_BROKEN_PROVIDER = """\
    from repolish import (
        BaseContext,
        BaseInputs,
        FinalizeContextOptions,
        Provider,
        TemplateMapping,
    )

    class Ctx(BaseContext):
        title: str = 'pre-finalize'

    class P(Provider[Ctx, BaseInputs]):
        def create_context(self):
            return Ctx()

        def finalize_context(self, opt: FinalizeContextOptions[Ctx, BaseInputs]):
            raise RuntimeError('finalize boom')

        def create_file_mappings(self, context):
            return {'OUT.md': TemplateMapping(source_template='OUT.md.jinja')}
    """


def test_broken_provider_finalize_keeps_pre_finalize_context(
    tmp_path: Path,
) -> None:
    """The provider path no longer aborts the run: finalize failure is rc 1.

    Pre-1.18 a raising provider finalize_context crashed the whole apply;
    now it matches the facet treatment: the pre-finalize context is kept,
    the failure is recorded, and the run finishes with exit 1.
    """
    mod, _ = _write_provider(
        tmp_path,
        _FINALIZE_BROKEN_PROVIDER,
        {'OUT.md.jinja': 'title: {{ title }}\n'},
    )
    result = _apply(mod.P, tmp_path, alias='finalize-broken')
    assert result.exit_code == 1
    (failure,) = result.session.providers.hook_failures
    assert failure.hook == 'finalize_context'
    assert failure.provider_id == result.session.alias_to_pid['finalize-broken']
    assert failure.alias == 'finalize-broken'
    # The file rendered from the pre-finalize context, not nothing.
    assert (tmp_path / 'project' / 'OUT.md').read_text(
        encoding='utf-8',
    ) == 'title: pre-finalize\n'


_CREATE_CONTEXT_BROKEN_PROVIDER = """\
    from repolish import BaseContext, BaseInputs, Provider

    class Ctx(BaseContext):
        pass

    class P(Provider[Ctx, BaseInputs]):
        def create_context(self):
            raise RuntimeError('context boom')
    """


def test_broken_create_context_exits_one_without_crashing(
    tmp_path: Path,
) -> None:
    mod, _ = _write_provider(tmp_path, _CREATE_CONTEXT_BROKEN_PROVIDER, {})
    result = _apply(mod.P, tmp_path, alias='ctx-broken')
    assert result.exit_code == 1
    (failure,) = result.session.providers.hook_failures
    assert failure.hook == 'create_context'
    assert failure.error == 'context boom'


_CLEAN_PROVIDER = """\
    from repolish import (
        BaseContext,
        BaseInputs,
        Provider,
        TemplateMapping,
    )

    class Ctx(BaseContext):
        title: str = 'final'

    class P(Provider[Ctx, BaseInputs]):
        def create_context(self):
            return Ctx()

        def create_file_mappings(self, context):
            return {'OUT.md': TemplateMapping(source_template='OUT.md.jinja')}
    """


def test_clean_run_records_no_failures_and_writes_no_reports(
    tmp_path: Path,
) -> None:
    """The happy path: no failures on the bundle, no hook-failures directory."""
    mod, _ = _write_provider(
        tmp_path,
        _CLEAN_PROVIDER,
        {'OUT.md.jinja': 'title: {{ title }}\n'},
    )
    result = _apply(mod.P, tmp_path, alias='clean')
    assert result.exit_code == 0
    assert result.session.providers.hook_failures == []
    assert not (tmp_path / 'project' / '.repolish' / '_' / 'hook-failures').exists()


def test_bundle_defaults_hook_failures_to_empty() -> None:
    assert SessionBundle().hook_failures == []
