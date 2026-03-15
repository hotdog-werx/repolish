"""Integration tests for file_mappings driven through the scaffold-provider.

End-to-end scenarios (via ``repolish apply`` / ``repolish apply --check``):
- Mapped ``_repolish.*`` sources are applied to their declared destinations.
- The correct variant is selected when multiple sources are available.
- Stale mapped destinations are updated by ``repolish apply``.
- ``_repolish.*`` source files never appear verbatim in the project directory.
- ``repolish apply --check`` exits non-zero when a mapped destination is absent.
- ``repolish apply --check`` exits non-zero when a mapped destination is stale.
- ``repolish apply --check`` exits zero when every mapped destination is current.
- Nested mapped files (under ``.github/workflows/``) behave identically to
  root-level mapped files.

Loader / hydration-level tests (internal APIs, no CLI equivalent):
- ``check_generated_output`` reports ``MAPPING_SOURCE_MISSING`` when the source
  template file referenced by a mapping does not exist.
- ``apply_generated_output`` logs a warning and skips the destination when the
  mapping source is absent.
- Regular (non-prefixed) files used as mapping sources are excluded from normal
  copy/check iteration.
- ``create_providers`` merges ``file_mappings`` from multiple providers.
- A later provider overrides an earlier provider's mapping for the same key.
- A ``None`` value in ``create_file_mappings`` populates ``suppressed_sources``
  rather than ``file_mappings``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from repolish.hydration import apply_generated_output, check_generated_output
from repolish.loader import Providers, create_providers

from .conftest import fixtures, run_repolish

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from .conftest import InstalledProviders


def test_apply_creates_mapped_file_for_variant_a(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply on a fresh project creates config.yml from the variant-a source."""
    repo = fixtures.file_mappings_variant_a_fresh.stage(tmp_path)
    monkeypatch.chdir(repo)

    run_repolish(['apply'])

    config = repo / 'config.yml'
    assert config.exists(), 'config.yml must be created by apply'
    assert 'option-a' in config.read_text(encoding='utf-8')


def test_apply_creates_mapped_file_for_variant_b(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply with config_variant=b writes option-b content to config.yml."""
    repo = fixtures.file_mappings_variant_b_fresh.stage(tmp_path)
    monkeypatch.chdir(repo)

    run_repolish(['apply'])

    config = repo / 'config.yml'
    assert config.exists(), 'config.yml must be created by apply'
    content = config.read_text(encoding='utf-8')
    assert 'option-b' in content
    assert 'option-a' not in content


def test_apply_updates_stale_mapped_destination(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second apply overwrites a stale config.yml with the template content."""
    repo = fixtures.file_mappings_variant_a_fresh.stage(tmp_path)
    monkeypatch.chdir(repo)

    run_repolish(['apply'])
    (repo / 'config.yml').write_text('stale: content\n', encoding='utf-8')
    run_repolish(['apply'])

    content = (repo / 'config.yml').read_text(encoding='utf-8')
    assert 'option-a' in content, 'apply must restore variant-a content'
    assert 'stale' not in content


def test_apply_does_not_copy_unmapped_repolish_prefix_files(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_repolish.* source files must never appear verbatim in the project."""
    repo = fixtures.file_mappings_variant_a_fresh.stage(tmp_path)
    monkeypatch.chdir(repo)

    run_repolish(['apply'])

    assert not (repo / '_repolish.config-a.yml').exists()
    assert not (repo / '_repolish.config-b.yml').exists()


def test_check_exits_nonzero_when_mapped_destination_missing(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check exits non-zero when the mapped destination has not been created yet."""
    repo = fixtures.file_mappings_variant_a_fresh.stage(tmp_path)
    monkeypatch.chdir(repo)

    result = run_repolish(['apply', '--check'], exit_code=2)
    assert 'MISSING' in result.output
    assert 'config.yml' in result.output


def test_check_exits_nonzero_when_mapped_destination_is_stale(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check exits non-zero when the mapped destination has stale content."""
    repo = fixtures.file_mappings_variant_a_fresh.stage(tmp_path)
    monkeypatch.chdir(repo)

    run_repolish(['apply'])
    (repo / 'config.yml').write_text('stale: content\n', encoding='utf-8')

    result = run_repolish(['apply', '--check'], exit_code=2)
    assert 'config.yml' in result.output
    assert 'stale' in result.output


def test_check_exits_zero_when_mapped_destination_is_current(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check exits zero when the mapped destination matches the template exactly."""
    repo = fixtures.file_mappings_variant_a_fresh.stage(tmp_path)
    monkeypatch.chdir(repo)

    run_repolish(['apply'])
    run_repolish(['apply', '--check'])


def test_check_exits_zero_when_mapped_destination_already_seeded(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check exits zero when the project already has the correctly-seeded config.yml."""
    repo = fixtures.file_mappings_variant_a_existing.stage(tmp_path)
    monkeypatch.chdir(repo)

    run_repolish(['apply', '--check'])


def test_apply_creates_nested_mapped_file(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply creates a mapped file that lives inside a nested sub-directory."""
    repo = fixtures.file_mappings_nested_ci_fresh.stage(tmp_path)
    monkeypatch.chdir(repo)

    run_repolish(['apply'])

    ci_file = repo / '.github' / 'workflows' / 'ci.yml'
    assert ci_file.exists(), '.github/workflows/ci.yml should be created by apply'
    assert 'name: ci' in ci_file.read_text(encoding='utf-8')


def test_apply_nested_does_not_copy_repolish_prefix_source(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_repolish.* sources inside sub-directories are not copied verbatim."""
    repo = fixtures.file_mappings_nested_ci_fresh.stage(tmp_path)
    monkeypatch.chdir(repo)

    run_repolish(['apply'])

    workflows = repo / '.github' / 'workflows'
    assert not (workflows / '_repolish.ci-github.yml').exists()


def test_check_exits_nonzero_when_nested_mapped_destination_missing(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check exits non-zero when a nested mapped destination does not exist yet."""
    repo = fixtures.file_mappings_nested_ci_fresh.stage(tmp_path)
    monkeypatch.chdir(repo)

    result = run_repolish(['apply', '--check'], exit_code=2)
    assert 'MISSING' in result.output
    assert '.github/workflows/ci.yml' in result.output


def test_check_exits_zero_when_nested_mapped_destination_is_current(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check exits zero when a nested mapped destination matches the template."""
    repo = fixtures.file_mappings_nested_ci_fresh.stage(tmp_path)
    monkeypatch.chdir(repo)

    run_repolish(['apply'])
    run_repolish(['apply', '--check'])


# ---------------------------------------------------------------------------
# Loader / hydration-level tests (no CLI equivalent)
# ---------------------------------------------------------------------------


def test_check_reports_mapping_source_missing(tmp_path: Path) -> None:
    """check_generated_output reports MAPPING_SOURCE_MISSING for a missing source.

    The source file referenced by a mapping does not exist in the render output.
    Exercises the distinct error path compared to a missing destination.
    """
    setup_output = tmp_path / 'setup-output'
    (setup_output / 'repolish').mkdir(parents=True)

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    providers = Providers(
        anchors={},
        delete_files=[],
        file_mappings={'config.yml': '_repolish.missing.yml'},
        delete_history={},
    )

    diffs = check_generated_output(setup_output, providers, base_dir)

    assert len(diffs) == 1
    rel, msg = diffs[0]
    assert rel == 'config.yml'
    assert 'MAPPING_SOURCE_MISSING' in msg
    assert '_repolish.missing.yml' in msg


def test_apply_warns_when_mapped_source_missing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """apply_generated_output logs a warning and skips the destination.

    Triggered when the source file referenced by a mapping does not exist.
    """
    setup_output = tmp_path / 'setup-output'
    (setup_output / 'repolish').mkdir(parents=True)

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    providers = Providers(
        anchors={},
        delete_files=[],
        file_mappings={'config.yml': '_repolish.missing.yml'},
        delete_history={},
    )

    apply_generated_output(setup_output, providers, base_dir)

    captured = capsys.readouterr()
    assert 'file_mapping_source_not_found' in captured.out
    assert '_repolish.missing.yml' in captured.out
    assert not (base_dir / 'config.yml').exists()


def test_check_skips_regular_file_used_as_mapping_source(
    tmp_path: Path,
) -> None:
    """check_generated_output does not flag a non-prefixed source file as missing.

    When the file appears as a mapping value it is excluded from the normal
    check iteration and the mapped destination is compared instead.
    """
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)
    (repolish_dir / 'template-config.yml').write_text('template content')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()
    (base_dir / 'final-config.yml').write_text('template content')

    providers = Providers(
        anchors={},
        delete_files=[],
        file_mappings={'final-config.yml': 'template-config.yml'},
        delete_history={},
    )

    diffs = check_generated_output(setup_output, providers, base_dir)
    assert len(diffs) == 0


def test_apply_skips_regular_file_used_as_mapping_source(
    tmp_path: Path,
) -> None:
    """apply_generated_output copies the mapped destination only.

    The source file must not also be copied to its original path when it
    appears as a mapping value.
    """
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)
    (repolish_dir / 'template-config.yml').write_text('template content')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    providers = Providers(
        anchors={},
        delete_files=[],
        file_mappings={'final-config.yml': 'template-config.yml'},
        delete_history={},
    )

    apply_generated_output(setup_output, providers, base_dir)

    assert (base_dir / 'final-config.yml').read_text() == 'template content'
    assert not (base_dir / 'template-config.yml').exists()


def test_file_mappings_merge_across_providers(tmp_path: Path) -> None:
    """file_mappings from multiple providers are merged into one dict."""
    template_a = tmp_path / 'template_a'
    template_a.mkdir()
    template_b = tmp_path / 'template_b'
    template_b.mkdir()

    (template_a / 'repolish.py').write_text("""
from repolish import BaseContext, Provider, BaseInputs

class Ctx(BaseContext):
    pass

class P(Provider[Ctx, BaseInputs]):
    def create_context(self):
        return Ctx()

    def create_file_mappings(self, context=None):
        return {'file-a.yml': '_repolish.a.yml'}
""")
    (template_b / 'repolish.py').write_text("""
from repolish import BaseContext, Provider, BaseInputs

class Ctx(BaseContext):
    pass

class P(Provider[Ctx, BaseInputs]):
    def create_context(self):
        return Ctx()

    def create_file_mappings(self, context=None):
        return {'file-b.yml': '_repolish.b.yml'}
""")

    providers = create_providers([str(template_a), str(template_b)])

    assert providers.file_mappings == {
        'file-a.yml': '_repolish.a.yml',
        'file-b.yml': '_repolish.b.yml',
    }


def test_file_mappings_later_provider_overrides_earlier(tmp_path: Path) -> None:
    """A later provider's mapping overrides an earlier one for the same key."""
    template_a = tmp_path / 'template_a'
    template_a.mkdir()
    template_b = tmp_path / 'template_b'
    template_b.mkdir()

    (template_a / 'repolish.py').write_text("""
from repolish import BaseContext, Provider, BaseInputs

class Ctx(BaseContext):
    pass

class P(Provider[Ctx, BaseInputs]):
    def create_context(self):
        return Ctx()

    def create_file_mappings(self, context=None):
        return {'config.yml': '_repolish.option-a.yml'}
""")
    (template_b / 'repolish.py').write_text("""
from repolish import BaseContext, Provider, BaseInputs

class Ctx(BaseContext):
    pass

class P(Provider[Ctx, BaseInputs]):
    def create_context(self):
        return Ctx()

    def create_file_mappings(self, context=None):
        return {'config.yml': '_repolish.option-b.yml'}
""")

    providers = create_providers([str(template_a), str(template_b)])

    assert providers.file_mappings == {'config.yml': '_repolish.option-b.yml'}


def test_none_mapped_entry_populates_suppressed_sources(tmp_path: Path) -> None:
    """A None value in create_file_mappings populates suppressed_sources.

    The key must not appear in file_mappings — the provider explicitly opted
    out of managing that path this run.
    """
    template = tmp_path / 'prov'
    template.mkdir()
    (template / 'repolish.py').write_text("""
from repolish import BaseContext, Provider, BaseInputs

class Ctx(BaseContext):
    pass

class P(Provider[Ctx, BaseInputs]):
    def create_context(self):
        return Ctx()

    def create_file_mappings(self, context=None):
        return {
            '.github/workflows/_ci-checks.yaml': None,
            'other.txt': '_repolish.other.txt',
        }
""")

    providers = create_providers([str(template)])

    assert '.github/workflows/_ci-checks.yaml' not in providers.file_mappings
    assert '.github/workflows/_ci-checks.yaml' in providers.suppressed_sources
    assert 'other.txt' in providers.file_mappings
