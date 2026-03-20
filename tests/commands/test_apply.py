import textwrap
from pathlib import Path

from pytest_mock import MockerFixture

from repolish.commands.apply.session import (
    run_session as run_repolish,
)
from repolish.commands.apply.display import (
    print_files_summary as _print_files_summary,
)
from repolish.commands.apply.options import ApplyOptions
from repolish.config.models import RepolishConfig, ResolvedProviderInfo
from repolish.config.models.provider import ProviderSymlink
from repolish.linker.health import ProviderReadinessResult
from repolish.providers import SessionBundle
from repolish.providers.models import (
    Action,
    BaseContext,
    Decision,
    FileMode,
    TemplateMapping,
)


def write_file(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding='utf-8')


def make_template_with_binary(base: Path, name: str) -> None:
    tpl_dir = base / name
    repo_dir = tpl_dir / 'repolish'
    repo_dir.mkdir(parents=True, exist_ok=True)
    write_file(
        repo_dir / 'file_a.md',
        textwrap.dedent("""\
    ## repolish-start[readme]
    Default readme
    repolish-end[readme]
    """),
    )
    write_file(repo_dir / 'file_b.toml', 'key = "value"\n')
    # binary logo
    (repo_dir / 'logo.png').write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00\x00')
    # provider
    rep = tpl_dir / 'repolish.py'
    rep.write_text(
        textwrap.dedent("""\
    def create_context():
        return {'repo': {'name': 'test_repo'}}

    def create_delete_files():
        # Use a POSIX-style nested path to ensure path normalization works
        # across platforms (e.g. path/to/file.txt -> path\to\file.txt on Windows)
        return ['path/to/file.txt', 'temp']
    """),
    )


def make_template_with_unreadable(base: Path, name: str) -> None:
    tpl_dir = base / name
    repo_dir = tpl_dir / 'repolish'
    repo_dir.mkdir(parents=True, exist_ok=True)
    p = repo_dir / 'secret.txt'
    write_file(p, 'top secret')
    rep = tpl_dir / 'repolish.py'
    rep.write_text(
        textwrap.dedent("""\
    def create_context():
        return {'repo': {'name': 'test_repo'}}
    """),
    )


def test_apply_command_handles_missing_provider_and_extra_directory(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Ensure the `providers_order` logic continues when an alias is missing and still appends any stray directories.

    This exercises the two uncovered lines in `repolish/commands/apply.py`:
    - skipping an alias when `config.providers` lacks the entry (line 54)
    - appending an extra directory tuple for entries not already in `template_dirs` (line 63)
    """
    # prepare a dummy config file path (contents unused thanks to mocker.patch)
    cfg_path = tmp_path / 'repolish.yaml'
    cfg_path.write_text('')

    fake_config = RepolishConfig(
        config_dir=tmp_path,
        providers_order=['missing'],
        providers={},
        template_overrides={'foo': 'bar'},
    )

    mocker.patch(
        'repolish.commands.apply.pipeline.load_config',
    ).return_value = fake_config
    mocker.patch(
        'repolish.commands.apply.session.prepare_staging',
    ).return_value = (tmp_path, tmp_path / 'in', tmp_path / 'out')

    recorded: dict[str, object] = {}

    # helper stub for template generation
    def fake_create(
        staging: Path,
        template_dirs: list[tuple[str | None, Path]],
        template_overrides: dict[str, str] | None = None,
        excluded_sources: set[str] | None = None,
    ) -> None:
        recorded['template_dirs'] = template_dirs
        recorded['overrides'] = template_overrides

    mocker.patch(
        'repolish.commands.apply.staging.stage_templates',
        fake_create,
    )

    mocker.patch(
        'repolish.commands.apply.pipeline.build_final_providers',
    ).return_value = SessionBundle(
        delete_files=[],
        delete_history={},
        create_only_files=[],
        file_mappings={},
        provider_contexts={},
    )
    mocker.patch(
        'repolish.commands.apply.session.preprocess_templates',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.check.render_template',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.check.check_generated_output',
    ).return_value = []
    mocker.patch(
        'repolish.commands.apply.session.apply_generated_output',
    ).return_value = None

    rv = run_repolish(ApplyOptions(config_path=cfg_path, check_only=False))
    assert rv == 0

    # verify branch behaviour: missing provider skipped (no directories available)
    assert recorded['template_dirs'] == []
    assert recorded['overrides'] == {'foo': 'bar'}


def test_apply_warns_when_providers_not_ready(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Ensure a warning is logged when ensure_providers_ready reports failures."""
    cfg_path = tmp_path / 'repolish.yaml'
    cfg_path.write_text('')

    # Override the autouse fixture to simulate a failed provider registration.
    mocker.patch(
        'repolish.commands.apply.pipeline.ensure_providers_ready',
        return_value=ProviderReadinessResult(ready=[], failed=['broken_lib']),
    )

    fake_config = RepolishConfig(
        config_dir=tmp_path,
        providers={},
    )
    mocker.patch(
        'repolish.commands.apply.pipeline.load_config',
    ).return_value = fake_config
    mocker.patch(
        'repolish.commands.apply.session.prepare_staging',
    ).return_value = (
        tmp_path,
        tmp_path / 'in',
        tmp_path / 'out',
    )
    mocker.patch(
        'repolish.commands.apply.staging.stage_templates',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.pipeline.build_final_providers',
    ).return_value = SessionBundle(
        provider_contexts={},
    )
    mocker.patch(
        'repolish.commands.apply.session.preprocess_templates',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.check.render_template',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.check.check_generated_output',
    ).return_value = []
    mocker.patch(
        'repolish.commands.apply.session.apply_generated_output',
    ).return_value = None

    rv = run_repolish(ApplyOptions(config_path=cfg_path, check_only=False))
    assert rv == 0


def test_apply_command_runs_with_valid_provider(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Exercise the apply command with a valid provider alias in providers_order."""
    cfg_path = tmp_path / 'repolish.yaml'
    cfg_path.write_text('')

    provider_dir = tmp_path / 'prov_a'
    fake_config = RepolishConfig(
        config_dir=tmp_path,
        providers_order=['prov_a'],
        providers={
            'prov_a': ResolvedProviderInfo(
                alias='prov_a',
                provider_root=provider_dir,
                resources_dir=provider_dir,
            ),
        },
    )

    mocker.patch(
        'repolish.commands.apply.pipeline.load_config',
    ).return_value = fake_config
    mocker.patch(
        'repolish.commands.apply.session.prepare_staging',
    ).return_value = (
        tmp_path,
        tmp_path / 'in',
        tmp_path / 'out',
    )
    mocker.patch(
        'repolish.commands.apply.staging.stage_templates',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.pipeline.build_final_providers',
    ).return_value = SessionBundle(
        provider_contexts={},
    )
    mocker.patch(
        'repolish.commands.apply.session.preprocess_templates',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.check.render_template',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.session.apply_generated_output',
    ).return_value = None

    rv = run_repolish(ApplyOptions(config_path=cfg_path, check_only=False))
    assert rv == 0


def test_apply_returns_1_when_render_fails(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """command() returns 1 and logs render_failed when render_template raises RuntimeError."""
    cfg_path = tmp_path / 'repolish.yaml'
    cfg_path.write_text('')

    fake_config = RepolishConfig(config_dir=tmp_path)

    mocker.patch(
        'repolish.commands.apply.pipeline.load_config',
    ).return_value = fake_config
    mocker.patch(
        'repolish.commands.apply.session.prepare_staging',
    ).return_value = (
        tmp_path,
        tmp_path / 'in',
        tmp_path / 'out',
    )
    mocker.patch(
        'repolish.commands.apply.staging.stage_templates',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.pipeline.build_final_providers',
    ).return_value = SessionBundle(
        provider_contexts={},
    )
    mocker.patch(
        'repolish.commands.apply.session.preprocess_templates',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.check.render_template',
    ).side_effect = RuntimeError(
        "template rendering errors:\npyproject.toml: 'some_unknown' is undefined",
    )

    rv = run_repolish(ApplyOptions(config_path=cfg_path, check_only=False))
    assert rv == 1


def test_check_only_with_diffs_returns_2(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Exercise the check_only path when diffs are detected.

    Lines 201-205: logger.error, rich_print_diffs and return 2 are only
    reached when check_only=True and check_generated_output returns diffs.
    """
    cfg_path = tmp_path / 'repolish.yaml'
    cfg_path.write_text('')

    fake_config = RepolishConfig(config_dir=tmp_path)

    mocker.patch(
        'repolish.commands.apply.pipeline.load_config',
    ).return_value = fake_config
    mocker.patch(
        'repolish.commands.apply.session.prepare_staging',
    ).return_value = (
        tmp_path,
        tmp_path / 'in',
        tmp_path / 'out',
    )
    mocker.patch(
        'repolish.commands.apply.staging.stage_templates',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.pipeline.build_final_providers',
    ).return_value = SessionBundle(
        provider_contexts={},
    )
    mocker.patch(
        'repolish.commands.apply.session.preprocess_templates',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.check.render_template',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.check.check_generated_output',
    ).return_value = ['some_diff']
    mocker.patch(
        'repolish.commands.apply.check.rich_print_diffs',
    ).return_value = None

    rv = run_repolish(ApplyOptions(config_path=cfg_path, check_only=True))
    assert rv == 2


def _base_mocks(
    mocker: MockerFixture,
    tmp_path: Path,
    fake_config: RepolishConfig,
    providers: SessionBundle,
) -> None:
    """Wire up the standard set of mocks used by the two coverage tests below."""
    mocker.patch(
        'repolish.commands.apply.pipeline.load_config',
    ).return_value = fake_config
    mocker.patch(
        'repolish.commands.apply.session.prepare_staging',
    ).return_value = (
        tmp_path,
        tmp_path / 'in',
        tmp_path / 'out',
    )
    mocker.patch(
        'repolish.commands.apply.staging.stage_templates',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.pipeline.build_final_providers',
    ).return_value = providers
    mocker.patch(
        'repolish.commands.apply.session.preprocess_templates',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.check.render_template',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.session.apply_generated_output',
    ).return_value = None


def test_apply_with_template_mapping_in_file_mappings(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Exercises the TemplateMapping branch inside _records_from_file_mappings.

    A provider uses create_file_mappings() and returns a TemplateMapping with
    source_provider set.  After build_final_providers the TemplateMapping object
    lives in providers.file_mappings; build_file_records must resolve the owner
    via pid_to_alias.
    """
    cfg_path = tmp_path / 'repolish.yaml'
    cfg_path.write_text('')

    provider_dir = tmp_path / 'prov_a'
    fake_config = RepolishConfig(
        config_dir=tmp_path,
        providers={
            'prov_a': ResolvedProviderInfo(
                alias='prov_a',
                provider_root=provider_dir,
                resources_dir=provider_dir,
            ),
        },
    )

    providers = SessionBundle(
        file_mappings={
            'report.md': TemplateMapping(
                source_template='report.md.jinja',
                file_mode=FileMode.REGULAR,
                source_provider=provider_dir.as_posix(),
            ),
            'legacy.txt': 'legacy.txt.jinja',
        },
    )

    _base_mocks(mocker, tmp_path, fake_config, providers)

    rv = run_repolish(ApplyOptions(config_path=cfg_path, check_only=False))
    assert rv == 0


def test_apply_with_delete_files(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Exercises the loop body inside _records_from_delete_files.

    A provider schedules files for deletion via create_delete_files().  After
    build_final_providers, providers.delete_files is non-empty.  Two sub-cases
    are present in a single run: one file has provenance in delete_history (owner
    resolves to the provider alias), and one file has no history entry (owner
    falls back to 'unknown').
    """
    cfg_path = tmp_path / 'repolish.yaml'
    cfg_path.write_text('')

    provider_dir = tmp_path / 'prov_a'
    fake_config = RepolishConfig(
        config_dir=tmp_path,
        providers={
            'prov_a': ResolvedProviderInfo(
                alias='prov_a',
                provider_root=provider_dir,
                resources_dir=provider_dir,
            ),
        },
    )

    providers = SessionBundle(
        delete_files=[Path('tracked.txt'), Path('untracked.txt')],
        delete_history={
            'tracked.txt': [
                Decision(source=provider_dir.as_posix(), action=Action.delete),
            ],
        },
    )

    _base_mocks(mocker, tmp_path, fake_config, providers)

    rv = run_repolish(ApplyOptions(config_path=cfg_path, check_only=False))
    assert rv == 0


def test_template_sources_translated_from_alias_to_pid(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """stage_templates returns alias as the source value; apply must translate to pid.

    When render_template is called the providers.template_sources values must be
    full provider directory paths (pids), not the short alias strings.  A mismatch
    causes _ctx_for_pid to return {} and every template variable becomes undefined.
    """
    cfg_path = tmp_path / 'repolish.yaml'
    cfg_path.write_text('')

    provider_dir = tmp_path / 'template_a'
    pid = provider_dir.as_posix()

    fake_config = RepolishConfig(
        config_dir=tmp_path,
        providers_order=['template_a'],
        providers={
            'template_a': ResolvedProviderInfo(
                alias='template_a',
                provider_root=provider_dir,
                resources_dir=provider_dir,
            ),
        },
    )

    providers = SessionBundle(provider_contexts={pid: BaseContext()})

    mocker.patch(
        'repolish.commands.apply.pipeline.load_config',
    ).return_value = fake_config
    mocker.patch(
        'repolish.commands.apply.session.prepare_staging',
    ).return_value = (
        tmp_path,
        tmp_path / 'in',
        tmp_path / 'out',
    )
    # stage_templates returns alias ('template_a') as the source value — the
    # raw output before the alias→pid translation in apply.command().
    mocker.patch(
        'repolish.commands.apply.staging.stage_templates',
    ).return_value = (
        tmp_path / 'staging',
        {'pyproject.toml': 'template_a', 'Dockerfile': 'template_a'},
    )
    mocker.patch(
        'repolish.commands.apply.pipeline.build_final_providers',
    ).return_value = providers
    mocker.patch(
        'repolish.commands.apply.session.preprocess_templates',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.session.apply_generated_output',
    ).return_value = None

    captured: dict[str, object] = {}

    def fake_render_template(
        setup_input: Path,
        p: SessionBundle,
        setup_output: Path,
    ) -> None:
        captured['template_sources'] = dict(p.template_sources)

    mocker.patch(
        'repolish.commands.apply.check.render_template',
        side_effect=fake_render_template,
    )

    rv = run_repolish(ApplyOptions(config_path=cfg_path, check_only=False))
    assert rv == 0

    # aliases must have been translated to pids before render_template is called
    assert captured['template_sources'] == {
        'pyproject.toml': pid,
        'Dockerfile': pid,
    }


def test_paused_files_logged_as_warning(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """When paused_files is non-empty a warning is emitted listing the files."""
    cfg_path = tmp_path / 'repolish.yaml'
    cfg_path.write_text('')

    provider_dir = tmp_path / 'template_a'
    fake_config = RepolishConfig(
        config_dir=tmp_path,
        providers_order=['template_a'],
        providers={
            'template_a': ResolvedProviderInfo(
                alias='template_a',
                provider_root=provider_dir,
                resources_dir=provider_dir,
            ),
        },
        paused_files=['src/generated.py', 'README.md'],
    )

    mocker.patch(
        'repolish.commands.apply.pipeline.load_config',
    ).return_value = fake_config
    mocker.patch(
        'repolish.commands.apply.session.prepare_staging',
    ).return_value = (
        tmp_path,
        tmp_path / 'in',
        tmp_path / 'out',
    )
    mocker.patch(
        'repolish.commands.apply.staging.stage_templates',
    ).return_value = (
        tmp_path / 'staging',
        {},
    )
    mocker.patch(
        'repolish.commands.apply.pipeline.build_final_providers',
    ).return_value = SessionBundle(
        provider_contexts={},
    )
    mocker.patch(
        'repolish.commands.apply.session.preprocess_templates',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.check.render_template',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.check.check_generated_output',
    ).return_value = []
    mocker.patch(
        'repolish.commands.apply.session.apply_generated_output',
    ).return_value = None

    mock_logger = mocker.patch('repolish.commands.apply.session.logger')

    run_repolish(ApplyOptions(config_path=cfg_path, check_only=False))

    warning_calls = [
        call for call in mock_logger.warning.call_args_list if call.args and call.args[0] == 'files_paused'
    ]
    assert warning_calls, 'expected a files_paused warning'
    assert set(warning_calls[0].kwargs['files']) == {
        'src/generated.py',
        'README.md',
    }


def test_print_files_summary_includes_symlink_only_provider(
    tmp_path: Path,
) -> None:
    """A provider with only symlinks (no file records) still appears in the table."""
    providers = SessionBundle(file_records=[])
    symlinks = {
        'symlink-only-provider': [
            ProviderSymlink(
                source=Path('src/file.txt'),
                target=Path('file.txt'),
            ),
        ],
    }
    # Should not raise; the symlink-only provider must appear in output.
    _print_files_summary(providers, symlinks)
