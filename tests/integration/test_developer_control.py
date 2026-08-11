"""Integration tests for developer control features.

Scenarios covered:
- paused_files skips a file during apply (file not written)
- paused_files skips a file during --check (no diff reported)
- template_overrides: null suppresses a file during apply
- template_overrides: null suppresses a file during --check
- template_overrides pins a file to a specific provider
- provider_root (local provider, no cli) supplies templates and is applied
"""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .conftest import init_git_repo, run_repolish

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding='utf-8')


def _inline_provider(directory: Path, files: dict[str, str]) -> None:
    """Create a minimal provider in ``directory`` that supplies the given files."""
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


# ---------------------------------------------------------------------------
# paused_files
# ---------------------------------------------------------------------------


@dataclass
class TCase:
    name: str
    initial_content: str
    provider_content: str
    paused: bool


def test_paused_file_is_not_written_by_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file listed in paused_files is not overwritten during apply."""
    _inline_provider(tmp_path / 'p', {'managed.txt': 'from provider\n'})
    _write(tmp_path / 'managed.txt', 'local content\n')

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {'p': {'provider_root': './p'}},
                'paused_files': ['managed.txt'],
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply'])

    assert (tmp_path / 'managed.txt').read_text(
        encoding='utf-8',
    ) == 'local content\n'


def test_paused_file_reports_no_diff_in_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file listed in paused_files produces no diff in --check even when content differs."""
    _inline_provider(tmp_path / 'p', {'managed.txt': 'from provider\n'})
    _write(tmp_path / 'managed.txt', 'local content\n')

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {'p': {'provider_root': './p'}},
                'paused_files': ['managed.txt'],
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    # exit_code=0 means no diff reported
    run_repolish(['apply', '--check'], exit_code=0)


def test_unpaused_file_is_written_by_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file NOT in paused_files is updated normally by apply."""
    _inline_provider(tmp_path / 'p', {'managed.txt': 'from provider\n'})
    _write(tmp_path / 'managed.txt', 'local content\n')

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps({'providers': {'p': {'provider_root': './p'}}}),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply'])

    assert (tmp_path / 'managed.txt').read_text(
        encoding='utf-8',
    ) == 'from provider\n'


# ---------------------------------------------------------------------------
# template_overrides: null — suppress a file
# ---------------------------------------------------------------------------


def test_suppressed_file_is_not_written_by_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file suppressed via template_overrides: null is not written during apply."""
    _inline_provider(tmp_path / 'p', {'owned.txt': 'from provider\n'})

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {'p': {'provider_root': './p'}},
                'template_overrides': {'owned.txt': None},
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply'])

    assert not (tmp_path / 'owned.txt').exists()


def test_suppressed_file_reports_no_diff_in_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file suppressed via template_overrides: null produces no diff in --check."""
    _inline_provider(tmp_path / 'p', {'owned.txt': 'from provider\n'})
    # Pre-create the file with different content — check should still pass
    _write(tmp_path / 'owned.txt', 'my own content\n')

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {'p': {'provider_root': './p'}},
                'template_overrides': {'owned.txt': None},
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply', '--check'], exit_code=0)


# ---------------------------------------------------------------------------
# local provider via provider_root (no cli)
# ---------------------------------------------------------------------------


def test_local_provider_root_supplies_templates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider configured with only provider_root applies its templates."""
    _inline_provider(tmp_path / 'local-p', {'hello.txt': 'hello from local\n'})

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps({'providers': {'local': {'provider_root': './local-p'}}}),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply'])

    assert (tmp_path / 'hello.txt').read_text(
        encoding='utf-8',
    ) == 'hello from local\n'


def test_local_provider_without_repolish_py_applies_templates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider_root without repolish.py still supplies template files."""
    # No repolish.py — only a template directory
    _write(tmp_path / 'local-p' / 'repolish' / 'plain.txt', 'plain content\n')

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps({'providers': {'local': {'provider_root': './local-p'}}}),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply'])

    assert (tmp_path / 'plain.txt').read_text(
        encoding='utf-8',
    ) == 'plain content\n'


# ---------------------------------------------------------------------------
# paused_files with multi-destination templates and keep-blocks
# ---------------------------------------------------------------------------


def test_paused_file_with_keepblocks_and_repolish_context_no_render_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A paused file with keep-blocks and repolish context doesn't cause render errors.

    This test verifies that when a file is paused, it's skipped during rendering
    entirely - so templates using {{ repolish.repo.owner }} or {{ env_name }}
    in a multi-destination with keep-blocks won't fail even if context is missing.

    The bug was that paused files were still being rendered, causing undefined
    variable errors. The fix skips paused files during both the generic Jinja
    pass and the template mapping pass.
    """
    # Create an inline provider with a multi-destination template
    _write(
        tmp_path / 'multi_provider' / 'repolish.py',
        """\
        from repolish import BaseContext, Provider, BaseInputs
        from repolish.providers.models import TemplateMapping

        class Ctx(BaseContext):
            pass

        class MultiProvider(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_mappings(self, context):
                return {
                    'paused.toml': TemplateMapping(
                        source_template='config.toml.jinja',
                        extra_context={'env_name': 'paused_env'},
                    ),
                    'active.toml': TemplateMapping(
                        source_template='config.toml.jinja',
                        extra_context={'env_name': 'active_env'},
                    ),
                }
        """,
    )

    # Template with keep-block AND repolish global context usage
    _write(
        tmp_path / 'multi_provider' / 'repolish' / 'config.toml.jinja',
        """\
        # Config for {{ repolish.repo.owner }}/{{ repolish.repo.name }}
        # Environment: {{ env_name }}

        ## repolish-keep-block[custom]: start="## CUSTOM_START" end="## CUSTOM_END"
        default_section:
          key: default_value
        ## CUSTOM_START
        # developer custom content here
        ## CUSTOM_END
        another_section: true
        """,
    )

    # Create paused.toml with developer modifications (will be paused)
    _write(
        tmp_path / 'paused.toml',
        """\
        # Paused config
        ## CUSTOM_START
        paused_specific:
          debug: true
        ## CUSTOM_END
        """,
    )

    # Create active.toml
    _write(
        tmp_path / 'active.toml',
        """\
        # Active config
        ## CUSTOM_START
        active_specific:
          debug: false
        ## CUSTOM_END
        """,
    )

    # Pause only paused.toml - it should not be rendered or overwritten
    _write(
        tmp_path / 'repolish.yaml',
        """\
        providers_order: ['multi_provider']
        providers:
          multi_provider:
            provider_root: ./multi_provider
        paused_files:
          - paused.toml
        """,
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path, owner='test-org', repo='test-repo')

    # This should NOT fail with "'env_name' is undefined" or "'repolish' is undefined"
    # because paused.toml is skipped during rendering
    result = run_repolish(['apply'])
    assert result.exit_code == 0, f'repolish apply failed: {result.output}'

    # paused.toml should keep its original content (not overwritten)
    paused_file = tmp_path / 'paused.toml'
    paused_text = paused_file.read_text()
    assert 'Paused config' in paused_text
    assert 'paused_specific:' in paused_text
    assert 'test-org/test-repo' not in paused_text  # Not rendered

    # active.toml should be updated with rendered content
    active_file = tmp_path / 'active.toml'
    active_text = active_file.read_text()
    assert 'test-org/test-repo' in active_text
    assert 'active_env' in active_text
    assert 'active_specific:' in active_text
