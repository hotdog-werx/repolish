"""End-to-end harness tests: the real apply pipeline against fixture projects.

`apply_provider` runs the production pipeline in a temp project — these
tests cover it the way a provider author would: fixture repos on disk,
assertions on the applied tree, and the idempotence guarantee.
"""

from __future__ import annotations

import importlib.util
import itertools
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

from repolish.providers.models import ValidationStatus
from repolish.testing import (
    apply_provider,
    assert_idempotent,
    stage_project,
)

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

    from repolish.providers.models.provider import Provider

_counter = itertools.count()


def _load_module(path: Path) -> ModuleType:
    """Import *path* under a unique name registered in ``sys.modules``.

    Registering the module matters twice over: ``_locate_templates_root``
    resolves the provider class's ``__module__`` through
    ``importlib.import_module``, and the pipeline's ``get_module`` reuses the
    already-loaded module instead of re-executing the file.
    """
    name = f'_e2e_fixture_provider_{next(_counter)}'
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_provider_pkg(
    base: Path,
    provider_code: str,
    templates: dict[str, str],
) -> type[Provider]:
    """Write a provider package under *base* and import its Provider class.

    The layout matches the packaged-provider convention the harness walks up
    to find: ``<pkg>/resources/templates/`` containing ``repolish.py`` and a
    ``repolish/`` template directory.
    """
    provider_root = base / 'pkg' / 'resources' / 'templates'
    (provider_root / 'repolish').mkdir(parents=True)
    (provider_root / 'repolish.py').write_text(
        textwrap.dedent(provider_code),
        encoding='utf-8',
    )
    for name, content in templates.items():
        target = provider_root / 'repolish' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(content), encoding='utf-8')
    mod = _load_module(provider_root / 'repolish.py')
    for val in vars(mod).values():
        if isinstance(val, type) and val.__module__ == mod.__name__ and hasattr(val, 'create_context'):
            return val
    msg = 'fixture provider module exports no Provider subclass'
    raise AssertionError(msg)


_BASE_PROVIDER = """\
    from repolish import BaseContext, BaseInputs, Provider

    class Ctx(BaseContext):
        pass

    class P(Provider[Ctx, BaseInputs]):
        def create_context(self):
            return Ctx()
    """


def test_apply_writes_templates_and_reports_status(tmp_path: Path) -> None:
    provider_cls = _make_provider_pkg(
        tmp_path,
        _BASE_PROVIDER,
        templates={
            'README.md.jinja': 'Welcome to {{ repolish.repo.owner }}/{{ repolish.repo.name }}\n',
        },
    )
    project = tmp_path / 'project'
    project.mkdir()

    result = apply_provider(provider_cls, project, alias='demo')

    assert result.exit_code == 0
    assert result.apply_result == {'README.md': 'written'}
    assert (project / 'README.md').read_text(encoding='utf-8') == ('Welcome to test-owner/test-repo\n')
    # Re-apply is a no-op with status 'unchanged'
    again = apply_provider(provider_cls, project, alias='demo')
    assert again.apply_result == {'README.md': 'unchanged'}


def test_project_files_excludes_scratch_dirs(tmp_path: Path) -> None:
    provider_cls = _make_provider_pkg(
        tmp_path,
        _BASE_PROVIDER,
        templates={'README.md.jinja': 'hello\n'},
    )
    project = tmp_path / 'project'
    project.mkdir()

    result = apply_provider(provider_cls, project)

    assert result.project_files() == {'README.md': 'hello\n'}
    # The run created .repolish/ scratch space inside the project
    assert (project / '.repolish').is_dir()
    assert result.render_tree == project / '.repolish' / '_' / 'render' / 'repolish'
    # Auto-staged templates keep their final name in the render tree
    assert result.render_tree.joinpath('README.md').is_file()


def test_check_only_reports_drift_then_idempotent(tmp_path: Path) -> None:
    provider_cls = _make_provider_pkg(
        tmp_path,
        _BASE_PROVIDER,
        templates={'README.md.jinja': 'hello\n'},
    )
    project = tmp_path / 'project'
    project.mkdir()

    drift = apply_provider(provider_cls, project, check_only=True)
    assert drift.exit_code == 2
    assert not (project / 'README.md').exists()

    assert_idempotent(provider_cls, project, alias='demo')
    assert (project / 'README.md').read_text(encoding='utf-8') == 'hello\n'


def test_insertions_into_developer_owned_file(tmp_path: Path) -> None:
    provider_code = """\
        from repolish import BaseContext, BaseInputs, Provider

        class Ctx(BaseContext):
            pass

        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_insertions(self, context):
                def display_year():
                    return '2026'
                return {'README.md': {'display-year': display_year}}
        """
    provider_cls = _make_provider_pkg(tmp_path, provider_code, templates={})
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'README.md').write_text(
        'hand-written intro\n\n<!-- repolish:on:year display-year -->\n<!-- repolish:off:year -->\n',
        encoding='utf-8',
    )

    result = apply_provider(provider_cls, project)

    assert result.exit_code == 0
    assert result.insertion_results['README.md'].total_blocks == 1
    assert result.insertion_results['README.md'].failed_blocks == 0
    assert (project / 'README.md').read_text(encoding='utf-8') == (
        'hand-written intro\n\n<!-- repolish:on:year display-year -->\n2026\n<!-- repolish:off:year -->\n'
    )


def test_validation_results_exposed(tmp_path: Path) -> None:
    """The pipeline collects validator failures; passes stay out of the way."""
    provider_code = """\
        from repolish import BaseContext, BaseInputs, Provider
        from repolish.providers.models import (
            FileValidatorOptions,
            FileValidatorSpec,
            ValidationResult,
            ValidationStatus,
        )

        class Ctx(BaseContext):
            pass

        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_validators(self, context):
                def header(context, path):
                    return ValidationResult(
                        status=ValidationStatus.ERROR,
                        message='missing ok header',
                        validator_name='header',
                    )
                return {'README.md': {
                    'header': header,
                    'off': FileValidatorSpec(
                        fn=header,
                        options=FileValidatorOptions(enabled=False),
                    ),
                }}
        """
    provider_cls = _make_provider_pkg(
        tmp_path,
        provider_code,
        templates={'README.md.jinja': 'hello\n'},
    )
    project = tmp_path / 'project'
    project.mkdir()

    result = apply_provider(provider_cls, project)

    # A failing validator fails the run and shows up in validation_results
    assert result.exit_code == 1
    per_file = result.validation_results['README.md']
    assert per_file['header'].status == ValidationStatus.ERROR
    assert per_file['header'].message == 'missing ok header'
    # Disabled validators are skipped entirely
    assert 'off' not in per_file


def test_config_merge_post_process_and_paused_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('CI', '1')
    provider_cls = _make_provider_pkg(
        tmp_path,
        _BASE_PROVIDER,
        templates={
            'README.md.jinja': 'hello\n',
            'legacy.txt.jinja': 'legacy\n',
        },
    )
    project = tmp_path / 'project'
    project.mkdir()

    result = apply_provider(
        provider_cls,
        project,
        config={
            # config= entries follow the repolish.yaml schema — post_process
            # entries are command strings, tokenized by the runner
            'post_process': [
                f"{sys.executable} -c \"from pathlib import Path; Path('stamped.txt').write_text('stamped\\n')\"",
            ],
            'paused_files': ['legacy.txt'],
            # The harness provider entry always wins over anything here
            'providers': {'bogus': {'provider_root': '/definitely/not/here'}},
        },
    )

    assert result.exit_code == 0
    # post_process ran inside the render tree and its output was applied
    assert (project / 'stamped.txt').read_text(encoding='utf-8') == 'stamped\n'
    assert result.apply_result['stamped.txt'] == 'written'
    # paused files are never written
    assert not (project / 'legacy.txt').exists()


def test_global_context_is_deterministic_without_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Owner/repo/year come from the harness, never from cwd or git."""
    provider_cls = _make_provider_pkg(
        tmp_path,
        _BASE_PROVIDER,
        templates={
            'README.md.jinja': '{{ repolish.repo.owner }}/{{ repolish.repo.name }} {{ repolish.year }}\n',
        },
    )
    project = tmp_path / 'project'
    project.mkdir()
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = apply_provider(
        provider_cls,
        project,
        repo_owner='acme',
        repo_name='widget',
        year=2024,
    )

    assert result.exit_code == 0
    assert (project / 'README.md').read_text(
        encoding='utf-8',
    ) == 'acme/widget 2024\n'


def test_stage_project_copies_fixture(tmp_path: Path) -> None:
    fixture = tmp_path / 'fixture-repo'
    (fixture / 'nested').mkdir(parents=True)
    (fixture / 'nested' / 'README.md').write_text(
        'fixture state\n',
        encoding='utf-8',
    )

    project = stage_project(fixture, tmp_path / 'project')

    assert project == tmp_path / 'project'
    assert (project / 'nested' / 'README.md').read_text(
        encoding='utf-8',
    ) == 'fixture state\n'
    assert not (project / '.git').exists()


def test_stage_project_git_init(tmp_path: Path) -> None:
    fixture = tmp_path / 'fixture-repo'
    fixture.mkdir()

    project = stage_project(fixture, tmp_path / 'project', git_init=True)

    assert (project / '.git').is_dir()


def test_copies_resolve_from_resources_root(tmp_path: Path) -> None:
    """Copy sources resolve from the resources root, not the templates dir.

    Mirrors a linked provider's registration: `resources_dir` is the package's
    `resources/` directory, and `create_default_copies` sources are relative
    to it. The copy file deliberately lives outside the templates tree.
    """
    provider_code = """\
        from repolish import BaseContext, BaseInputs, Provider
        from repolish.providers.models import ResourceCopy

        class Ctx(BaseContext):
            pass

        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_default_copies(self):
                return [ResourceCopy(source='configs/app.toml', target='app.toml')]
        """
    provider_cls = _make_provider_pkg(
        tmp_path,
        provider_code,
        templates={'README.md.jinja': 'hello\n'},
    )
    # The copy source sits under resources/, a sibling of templates/
    copy_source = tmp_path / 'pkg' / 'resources' / 'configs' / 'app.toml'
    copy_source.parent.mkdir(parents=True)
    copy_source.write_text('copied content\n', encoding='utf-8')
    project = tmp_path / 'project'
    project.mkdir()

    result = apply_provider(provider_cls, project)

    assert result.exit_code == 0
    assert (project / 'app.toml').read_text(
        encoding='utf-8',
    ) == 'copied content\n'


def test_hand_edit_drift_is_detected_then_healed(tmp_path: Path) -> None:
    """A hand edit surfaces as check drift; assert_idempotent heals it."""
    provider_cls = _make_provider_pkg(
        tmp_path,
        _BASE_PROVIDER,
        templates={'README.md.jinja': 'hello\n'},
    )
    project = tmp_path / 'project'
    project.mkdir()
    apply_provider(provider_cls, project)

    (project / 'README.md').write_text('hand edit\n', encoding='utf-8')
    drift = apply_provider(provider_cls, project, check_only=True)
    assert drift.exit_code == 2

    # assert_idempotent applies first (overwriting the hand edit) and then
    # verifies the check pass agrees with what was written.
    assert_idempotent(provider_cls, project)
    assert (project / 'README.md').read_text(encoding='utf-8') == 'hello\n'


def test_assert_idempotent_fails_when_apply_fails(tmp_path: Path) -> None:
    provider_code = """\
        from repolish import BaseContext, BaseInputs, Provider
        from repolish.providers.models import (
            FileValidatorOptions,
            FileValidatorSpec,
            ValidationResult,
            ValidationStatus,
        )

        class Ctx(BaseContext):
            pass

        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_validators(self, context):
                def header(context, path):
                    return ValidationResult(
                        status=ValidationStatus.ERROR,
                        message='always broken',
                        validator_name='header',
                    )
                return {'README.md': {'header': FileValidatorSpec(
                    fn=header,
                    options=FileValidatorOptions(),
                )}}
        """
    provider_cls = _make_provider_pkg(
        tmp_path,
        provider_code,
        templates={'README.md.jinja': 'hello\n'},
    )
    project = tmp_path / 'project'
    project.mkdir()

    with pytest.raises(AssertionError, match='apply failed with exit code 1'):
        assert_idempotent(provider_cls, project)


def test_assert_idempotent_fails_when_check_reports_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A post_process command with fresh output each run mimics a provider.

    The provider can't reproduce its own output, so the check pass reports
    drift.
    """
    monkeypatch.setenv('CI', '1')
    provider_cls = _make_provider_pkg(
        tmp_path,
        _BASE_PROVIDER,
        templates={'README.md.jinja': 'hello\n'},
    )
    project = tmp_path / 'project'
    project.mkdir()

    stamp = (
        f'{sys.executable} -c '
        '"from pathlib import Path; import time; '
        "Path('out.txt').write_text(str(time.time_ns()))\""
    )
    with pytest.raises(AssertionError, match='reported drift'):
        assert_idempotent(
            provider_cls,
            project,
            config={'post_process': [stamp]},
        )
