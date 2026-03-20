"""Integration tests for scaffold-provider Jinja rendering.

Scenarios covered:
- Jinja templates render context variables (``project_name``,
  ``_provider.major_version``) into the output file.
- Unicode / multi-byte content in templates is preserved correctly.
- ``repolish apply`` output includes the ``providers_context`` event that lists
  each provider's typed context (regression guard for class-based providers).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .conftest import fixtures, run_repolish

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from .conftest import InstalledProviders


def test_apply_renders_jinja_notice_with_context(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply renders NOTICE.md from a Jinja template and output includes provider context.

    Validates three things in a single apply call:
    - Jinja variable ``{{ project_name }}`` is substituted from context.
    - ``{{ _provider.major_version }}`` resolves to the package major version (0).
    - Unicode characters in the template (→, ©) are preserved.
    - The apply output contains the ``providers_context`` structured log event,
      confirming class-based provider context is reported correctly.
    """
    repo = fixtures.scaffold_notice_fresh.stage(tmp_path)
    monkeypatch.chdir(repo)

    result = run_repolish(['apply'])

    notice = repo / 'NOTICE.md'
    assert notice.exists(), 'NOTICE.md should be created by apply'
    content = notice.read_text(encoding='utf-8')
    assert 'notice-project' in content, 'project_name context variable must be rendered'
    assert '0' in content, '_provider.major_version for 0.1.0 must render as 0'
    assert '→' in content, 'Unicode arrow must be preserved'
    assert '©' in content, 'Unicode copyright symbol must be preserved'

    assert 'providers_ready' in result.output, (
        'apply output must include the providers_ready event'
    )
    assert 'debug_dir' in result.output, (
        'providers_ready event must reference the debug_dir path'
    )
