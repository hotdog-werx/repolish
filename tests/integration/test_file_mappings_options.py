"""Integration tests for config-level file_mappings options.

Scenarios covered:
- Provider-declared files are written when no config override is present
- Config disables a file mapping via the shortcut form (false)
- Config disables a file mapping via the full form ({enabled: false})
- Only the disabled file is absent; other files from the same provider still land
- The disabled file does not produce a "paused" marker in apply output
"""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from .conftest import init_git_repo, run_repolish

if TYPE_CHECKING:
    from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding='utf-8')


def _make_provider(directory: Path, files: dict[str, str]) -> None:
    """Create a minimal provider that maps each key → template content."""
    for name, content in files.items():
        _write(directory / 'repolish' / name, content)
    _write(
        directory / 'repolish.py',
        """\
        from repolish import BaseContext, Provider, BaseInputs

        class Ctx(BaseContext):
            pass

        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()
        """,
    )


@dataclass
class TCase:
    name: str
    config_file_mappings: dict | None
    expected_missing: list[str]
    expected_present: list[str]


@pytest.mark.parametrize(
    'case',
    [
        TCase(
            name='no_override_all_files_written',
            config_file_mappings=None,
            expected_missing=[],
            expected_present=['a.txt', 'b.txt'],
        ),
        TCase(
            name='shortcut_false_disables_one_file',
            config_file_mappings={'a.txt': False},
            expected_missing=['a.txt'],
            expected_present=['b.txt'],
        ),
        TCase(
            name='full_form_enabled_false_disables_one_file',
            config_file_mappings={'a.txt': {'enabled': False}},
            expected_missing=['a.txt'],
            expected_present=['b.txt'],
        ),
        TCase(
            name='both_files_disabled',
            config_file_mappings={'a.txt': False, 'b.txt': False},
            expected_missing=['a.txt', 'b.txt'],
            expected_present=[],
        ),
    ],
    ids=lambda c: c.name,
)
def test_file_mapping_disabled_via_config(
    case: TCase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_provider(
        tmp_path / 'p',
        files={'a.txt': 'content a\n', 'b.txt': 'content b\n'},
    )

    provider_config: dict[str, object] = {'provider_root': './p'}
    if case.config_file_mappings is not None:
        provider_config['overrides'] = {'file_mappings': case.config_file_mappings}

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps({'providers': {'p': provider_config}}),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'])

    for name in case.expected_present:
        assert (tmp_path / name).exists(), f'{name} should have been written'

    for name in case.expected_missing:
        assert not (tmp_path / name).exists(), f'{name} should not have been written'
        # The disabled file must not appear with the "paused" marker in output
        assert 'paused' not in result.output


def test_disabled_file_not_shown_as_paused_in_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file disabled via file_mappings.enabled=false is silently absent.

    Unlike paused_files (which shows a yellow ✗ and '(paused)' annotation),
    a disabled mapping never enters the session bundle and produces no marker.
    """
    _make_provider(
        tmp_path / 'p',
        files={'managed.txt': 'from provider\n', 'other.txt': 'other\n'},
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps({
            'providers': {
                'p': {
                    'provider_root': './p',
                    'overrides': {'file_mappings': {'managed.txt': False}},
                },
            },
        }),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'])

    assert not (tmp_path / 'managed.txt').exists()
    assert (tmp_path / 'other.txt').exists()
    assert 'paused' not in result.output


def _make_provider_with_explicit_mappings(
    directory: Path,
    *,
    default_enabled: bool,
) -> None:
    """Provider that explicitly declares a file_mapping with a provider-level enabled flag."""
    _write(directory / 'repolish' / 'opt_in.txt', 'opt-in content\n')
    _write(
        directory / 'repolish.py',
        f"""\
        from repolish import BaseContext, Provider, BaseInputs, TemplateMapping
        from repolish.providers.models import FileMappingOptions

        class Ctx(BaseContext):
            pass

        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_mappings(self, ctx):
                return {{
                    'opt_in.txt': TemplateMapping(
                        source_template='opt_in.txt',
                        options=FileMappingOptions(enabled={default_enabled}),
                    ),
                }}
        """,
    )


def test_provider_disabled_by_default_no_config_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider declares enabled=False in TemplateMapping.options; no config override.

    The file must not be written. This exercises the elif branch in
    _process_provider_fm where the provider's own options control the
    effective enabled state (no config_opts present).
    """
    _make_provider_with_explicit_mappings(tmp_path / 'p', default_enabled=False)

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps({'providers': {'p': {'provider_root': './p'}}}),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply'])

    assert not (tmp_path / 'opt_in.txt').exists()


def test_provider_disabled_by_default_config_re_enables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider declares enabled=False; config explicitly re-enables it.

    The config override takes precedence over the provider default and the
    file must be written.
    """
    _make_provider_with_explicit_mappings(tmp_path / 'p', default_enabled=False)

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps({
            'providers': {
                'p': {
                    'provider_root': './p',
                    'overrides': {'file_mappings': {'opt_in.txt': {'enabled': True}}},
                },
            },
        }),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply'])

    assert (tmp_path / 'opt_in.txt').exists()
    assert (tmp_path / 'opt_in.txt').read_text(encoding='utf-8') == 'opt-in content\n'
