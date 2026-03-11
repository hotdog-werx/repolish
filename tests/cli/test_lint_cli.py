from pathlib import Path

import pytest
from typer.testing import CliRunner

from repolish.cli.main import app

runner = CliRunner()

_CLASS_PROVIDER = """\
from repolish import BaseContext, Provider, BaseInputs

class Ctx(BaseContext):
    package_name: str = 'my-project'

class MyProvider(Provider[Ctx, BaseInputs]):
    def create_context(self) -> Ctx:
        return Ctx()
"""


def test_lint_cli_clean_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lint CLI entry point exercises run_cli_command and exits 0 for a clean provider."""
    provider_dir = tmp_path / 'provider'
    provider_dir.mkdir()
    (provider_dir / 'repolish.py').write_text(_CLASS_PROVIDER, encoding='utf-8')
    tpl_root = provider_dir / 'repolish'
    tpl_root.mkdir()
    (tpl_root / 'out.txt').write_text('{{ package_name }}\n', encoding='utf-8')

    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ['lint', str(provider_dir)])
    assert result.exit_code == 0
