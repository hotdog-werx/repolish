import textwrap
from pathlib import Path
from types import SimpleNamespace

from pytest_mock import MockerFixture

from repolish.commands.apply import command as run_repolish
from repolish.loader import Providers
from repolish.loader.models import Action, Decision, FileMode, TemplateMapping


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

    # fake resolved configuration object
    fake_config = SimpleNamespace(
        providers_order=['missing'],
        providers={},
        template_overrides={'foo': 'bar'},
        config_dir=tmp_path,
        anchors={},
        post_process=[],
        delete_files=[],
    )

    mocker.patch(
        'repolish.commands.apply.load_config',
    ).return_value = fake_config
    mocker.patch(
        'repolish.commands.apply.prepare_staging',
    ).return_value = (tmp_path, tmp_path / 'in', tmp_path / 'out')

    recorded: dict[str, object] = {}

    # helper stub for template generation
    def fake_create(
        staging: Path,
        template_dirs: list[tuple[str | None, Path]],
        template_overrides: dict[str, str] | None = None,
    ) -> None:
        recorded['template_dirs'] = template_dirs
        recorded['overrides'] = template_overrides

    mocker.patch(
        'repolish.commands.apply.stage_templates',
        fake_create,
    )

    mocker.patch(
        'repolish.commands.apply.build_final_providers',
    ).return_value = Providers(
        delete_files=[],
        delete_history={},
        create_only_files=[],
        file_mappings={},
        provider_contexts={},
    )
    mocker.patch(
        'repolish.commands.apply.preprocess_templates',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.render_template',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.check_generated_output',
    ).return_value = []
    mocker.patch(
        'repolish.commands.apply.apply_generated_output',
    ).return_value = None

    rv = run_repolish(cfg_path, check_only=False)
    assert rv == 0

    # verify branch behaviour: missing provider skipped (no directories available)
    assert recorded['template_dirs'] == []
    assert recorded['overrides'] == {'foo': 'bar'}


def test_apply_command_runs_with_valid_provider(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Exercise the apply command with a valid provider alias in providers_order."""
    cfg_path = tmp_path / 'repolish.yaml'
    cfg_path.write_text('')

    provider_dir = tmp_path / 'prov_a'
    fake_config = SimpleNamespace(
        providers_order=['prov_a'],
        providers={'prov_a': SimpleNamespace(target_dir=provider_dir)},
        template_overrides=None,
        config_dir=tmp_path,
        anchors={},
        post_process=[],
        delete_files=[],
    )

    mocker.patch(
        'repolish.commands.apply.load_config',
    ).return_value = fake_config
    mocker.patch('repolish.commands.apply.prepare_staging').return_value = (
        tmp_path,
        tmp_path / 'in',
        tmp_path / 'out',
    )
    mocker.patch(
        'repolish.commands.apply.stage_templates',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.build_final_providers',
    ).return_value = Providers(
        provider_contexts={},
    )
    mocker.patch(
        'repolish.commands.apply.preprocess_templates',
    ).return_value = None
    mocker.patch('repolish.commands.apply.render_template').return_value = None
    mocker.patch(
        'repolish.commands.apply.apply_generated_output',
    ).return_value = None

    rv = run_repolish(cfg_path, check_only=False)
    assert rv == 0


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

    fake_config = SimpleNamespace(
        providers_order=None,
        providers={},
        template_overrides=None,
        config_dir=tmp_path,
        anchors={},
        post_process=[],
        delete_files=[],
    )

    mocker.patch(
        'repolish.commands.apply.load_config',
    ).return_value = fake_config
    mocker.patch('repolish.commands.apply.prepare_staging').return_value = (
        tmp_path,
        tmp_path / 'in',
        tmp_path / 'out',
    )
    mocker.patch(
        'repolish.commands.apply.stage_templates',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.build_final_providers',
    ).return_value = Providers(
        provider_contexts={},
    )
    mocker.patch(
        'repolish.commands.apply.preprocess_templates',
    ).return_value = None
    mocker.patch('repolish.commands.apply.render_template').return_value = None
    mocker.patch(
        'repolish.commands.apply.check_generated_output',
    ).return_value = ['some_diff']
    mocker.patch('repolish.commands.apply.rich_print_diffs').return_value = None

    rv = run_repolish(cfg_path, check_only=True)
    assert rv == 2


def _base_mocks(
    mocker: MockerFixture,
    tmp_path: Path,
    fake_config: object,
    providers: Providers,
) -> None:
    """Wire up the standard set of mocks used by the two coverage tests below."""
    mocker.patch(
        'repolish.commands.apply.load_config',
    ).return_value = fake_config
    mocker.patch('repolish.commands.apply.prepare_staging').return_value = (
        tmp_path,
        tmp_path / 'in',
        tmp_path / 'out',
    )
    mocker.patch(
        'repolish.commands.apply.stage_templates',
    ).return_value = None
    mocker.patch(
        'repolish.commands.apply.build_final_providers',
    ).return_value = providers
    mocker.patch(
        'repolish.commands.apply.preprocess_templates',
    ).return_value = None
    mocker.patch('repolish.commands.apply.render_template').return_value = None
    mocker.patch(
        'repolish.commands.apply.apply_generated_output',
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
    fake_config = SimpleNamespace(
        providers_order=None,
        providers={'prov_a': SimpleNamespace(target_dir=provider_dir)},
        template_overrides=None,
        config_dir=tmp_path,
        anchors={},
        post_process=[],
        delete_files=[],
    )

    providers = Providers(
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

    rv = run_repolish(cfg_path, check_only=False)
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
    fake_config = SimpleNamespace(
        providers_order=None,
        providers={'prov_a': SimpleNamespace(target_dir=provider_dir)},
        template_overrides=None,
        config_dir=tmp_path,
        anchors={},
        post_process=[],
        delete_files=[],
    )

    providers = Providers(
        delete_files=[Path('tracked.txt'), Path('untracked.txt')],
        delete_history={
            'tracked.txt': [
                Decision(source=provider_dir.as_posix(), action=Action.delete),
            ],
        },
    )

    _base_mocks(mocker, tmp_path, fake_config, providers)

    rv = run_repolish(cfg_path, check_only=False)
    assert rv == 0
