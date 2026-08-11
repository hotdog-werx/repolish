"""Integration test for multi-destination templates with repolish global context.

This test verifies that templates using {{ repolish.repo.owner }} and
{{ repolish.repo.name }} work correctly when a single template maps to
multiple destinations with different extra_context values.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

from .conftest import init_git_repo, run_repolish

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _write(path: Path, text: str) -> None:
    """Write text to a file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding='utf-8')


def test_multi_destination_with_repolish_context_no_keepblocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multi-destination templates WITHOUT keep-blocks work correctly.

    This is the baseline case: a single template maps to multiple destinations
    with different extra_context, but there are NO keep-blocks so no
    _preproc_* files are created. The template uses {{ repolish.repo.owner }}
    and {{ repolish.repo.name }} from the global context.

    This test SHOULD pass - the bug only manifests when keep-blocks trigger
    the creation of _preproc_* files.
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
                # Single template maps to multiple destinations with different extra_context
                return {
                    'dev.yaml': TemplateMapping(
                        source_template='config.yaml.jinja',
                        extra_context={'environment': 'development', 'debug': True},
                    ),
                    'prod.yaml': TemplateMapping(
                        source_template='config.yaml.jinja',
                        extra_context={'environment': 'production', 'debug': False},
                    ),
                }
        """,
    )

    # Template uses both repolish global context AND per-destination extra_context
    # NO keep-blocks, so no _preproc_* files will be created
    _write(
        tmp_path / 'multi_provider' / 'repolish' / 'config.yaml.jinja',
        """\
        # Config for {{ repolish.repo.owner }}/{{ repolish.repo.name }}
        environment: {{ environment }}
        debug: {{ debug }}
        """,
    )

    _write(
        tmp_path / 'repolish.yaml',
        """\
        providers_order: ['multi_provider']
        providers:
          multi_provider:
            provider_root: ./multi_provider
        """,
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path, owner='test-org', repo='test-repo')

    # Run repolish apply
    result = run_repolish(['apply'])
    assert result.exit_code == 0, f'repolish apply failed: {result.output}'

    # Verify dev.yaml has both repolish context and extra_context
    dev_file = tmp_path / 'dev.yaml'
    assert dev_file.exists(), 'dev.yaml should be created'
    dev_text = dev_file.read_text()
    assert 'test-org/test-repo' in dev_text, f'repolish.repo should be available: {dev_text}'
    assert 'environment: development' in dev_text, f'extra_context environment: {dev_text}'
    assert 'debug: true' in dev_text.lower(), f'extra_context debug: {dev_text}'

    # Verify prod.yaml has both repolish context and different extra_context
    prod_file = tmp_path / 'prod.yaml'
    assert prod_file.exists(), 'prod.yaml should be created'
    prod_text = prod_file.read_text()
    assert 'test-org/test-repo' in prod_text, f'repolish.repo should be available: {prod_text}'
    assert 'environment: production' in prod_text, f'extra_context environment: {prod_text}'
    assert 'debug: false' in prod_text.lower(), f'extra_context debug: {prod_text}'


def test_multi_destination_with_keepblocks_and_repolish_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multi-destination templates WITH keep-blocks can access repolish context.

    This test reproduces the bug: when a template has keep-blocks (e.g.,
    repolish-keep-block), the preprocessing step creates separate _preproc_*
    copies for each destination. The bug is that these _preproc_* files don't
    have their provider context registered in template_sources, so variables
    like {{ repolish.repo.owner }} and {{ generated_header }} become undefined.

    A provider ships a single template that maps to multiple destinations
    (dev.toml, prod.toml) with different keep-block content. The template uses
    {{ repolish.repo.owner }}/{{ repolish.repo.name }} from global context.
    """
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
                # Single template maps to multiple destinations with different extra_context
                return {
                    'dev.toml': TemplateMapping(
                        source_template='config.toml.jinja',
                        extra_context={'env_name': 'development'},
                    ),
                    'prod.toml': TemplateMapping(
                        source_template='config.toml.jinja',
                        extra_context={'env_name': 'production'},
                    ),
                }
        """,
    )

    # Template with keep-block AND repolish global context usage
    # This triggers creation of _preproc_* files during preprocessing
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

    # Create dev.toml with developer modifications (triggers keep-block extraction)
    _write(
        tmp_path / 'dev.toml',
        """\
        # Dev config
        ## CUSTOM_START
        dev_specific:
          debug: true
          log_level: verbose
        ## CUSTOM_END
        """,
    )

    # Create prod.toml with different developer modifications
    _write(
        tmp_path / 'prod.toml',
        """\
        # Prod config
        ## CUSTOM_START
        prod_specific:
          debug: false
          log_level: error
        ## CUSTOM_END
        """,
    )

    _write(
        tmp_path / 'repolish.yaml',
        """\
        providers_order: ['multi_provider']
        providers:
          multi_provider:
            provider_root: ./multi_provider
        """,
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path, owner='test-org', repo='test-repo')

    # Run repolish apply - this should trigger the bug
    # _preproc_* files will be created but template_sources won't have them
    result = run_repolish(['apply'])
    assert result.exit_code == 0, f'repolish apply failed: {result.output}'

    # Verify dev.toml has repolish context (bug would cause 'UnknownOwner/UnknownRepo' or undefined error)
    dev_file = tmp_path / 'dev.toml'
    assert dev_file.exists(), 'dev.toml should be created'
    dev_text = dev_file.read_text()
    assert 'test-org/test-repo' in dev_text, f'repolish.repo should be available: {dev_text}'
    assert 'dev_specific:' in dev_text, f'keep-block content should be preserved: {dev_text}'

    # Verify prod.toml has repolish context
    prod_file = tmp_path / 'prod.toml'
    assert prod_file.exists(), 'prod.toml should be created'
    prod_text = prod_file.read_text()
    assert 'test-org/test-repo' in prod_text, f'repolish.repo should be available: {prod_text}'
    assert 'prod_specific:' in prod_text, f'keep-block content should be preserved: {prod_text}'


def test_multi_destination_same_content_when_extra_context_identical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When extra_context is identical, both destinations get same rendered content.

    This verifies the baseline case: if two destinations have the same
    extra_context, they should produce identical output (aside from being
    separate files).
    """
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
                    'file-a.txt': TemplateMapping(
                        source_template='template.txt.jinja',
                        extra_context={'value': 'same'},
                    ),
                    'file-b.txt': TemplateMapping(
                        source_template='template.txt.jinja',
                        extra_context={'value': 'same'},
                    ),
                }
        """,
    )

    _write(
        tmp_path / 'multi_provider' / 'repolish' / 'template.txt.jinja',
        """\
        Repo: {{ repolish.repo.owner }}/{{ repolish.repo.name }}
        Value: {{ value }}
        """,
    )

    _write(
        tmp_path / 'repolish.yaml',
        """\
        providers_order: ['multi_provider']
        providers:
          multi_provider:
            provider_root: ./multi_provider
        """,
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path, owner='myorg', repo='myrepo')

    result = run_repolish(['apply'])
    assert result.exit_code == 0, f'repolish apply failed: {result.output}'

    # Both files should exist and have identical content
    file_a = tmp_path / 'file-a.txt'
    file_b = tmp_path / 'file-b.txt'
    assert file_a.exists()
    assert file_b.exists()
    assert file_a.read_text() == file_b.read_text(), 'Identical extra_context should produce identical output'
    assert 'myorg/myrepo' in file_a.read_text()
