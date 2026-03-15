"""Integration tests for the simple-provider example package.

Covers the three main integration surfaces for an installed provider:
- CLI: ``simple-provider-link --info`` returns valid ``ProviderInfo`` JSON.
- Loader: ``create_providers`` discovers and loads ``SimpleProvider``.
- Apply: ``repolish apply`` renders the expected output files in a fixture repo.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

from repolish.config.models import ProviderInfo
from repolish.loader.orchestrator import create_providers

from .conftest import fixtures, run_repolish

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from .conftest import InstalledProviders


def test_simple_provider_cli_info(
    installed_providers: InstalledProviders,
) -> None:
    """``simple-provider-link --info`` returns JSON that validates as ProviderInfo."""
    cli = installed_providers.venv_bin / 'simple-provider-link'
    result = subprocess.run(  # noqa: S603 - we're not passing user input to the shell
        [str(cli), '--info'],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    info = ProviderInfo.model_validate(data)
    # provider_root must point to the templates subdirectory
    assert 'templates' in info.provider_root
    assert info.site_package_dir != ''


def test_simple_provider_loads_via_create_providers(
    installed_providers: InstalledProviders,
) -> None:
    """``create_providers`` can load SimpleProvider from the installed package."""
    providers = create_providers(
        [str(installed_providers.simple_provider_root)],
    )
    assert providers is not None
    # SimpleProvider.create_anchors returns {'simple-provider-greeting': ...}
    assert 'simple-provider-greeting' in providers.anchors
    assert providers.anchors['simple-provider-greeting'] == 'hello from simple_provider'


def test_repolish_apply_creates_readme(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``repolish apply`` on a simple-repo fixture produces the expected README."""
    repo = fixtures.simple_repo.stage(tmp_path)

    monkeypatch.chdir(repo)
    _ = run_repolish(['apply'])

    readme = repo / 'README.simple-provider.md'
    assert readme.exists(), 'README.simple-provider.md was not created by repolish apply'
    content = readme.read_text(encoding='utf-8')
    assert 'Hello, world!' in content
