import textwrap
from pathlib import Path
from types import SimpleNamespace

from pytest_mock import MockerFixture

from repolish.commands.apply import command as run_repolish


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
        return {'repo_name': 'test_repo'}

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
        return {'repo_name': 'test_repo'}
    """),
    )


# deprecated test moved to tests/deprecated/commands/test_apply_directories.py
# (exercise deprecated `directories` config in CLI apply flow)

# deprecated test moved to tests/deprecated/commands/test_apply_directories.py
# (CLI check-mode test that uses the deprecated `directories` config key)


def test_apply_command_handles_missing_provider_and_extra_directory(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Ensure the `providers_order` logic continues when an alias is missing and still appends any stray directories.

    This exercises the two uncovered lines in ``repolish/commands/apply.py``:
    - skipping an alias when ``config.providers`` lacks the entry (line 54)
    - appending an extra directory tuple for entries not already in ``template_dirs`` (line 63)
    """
    # prepare a dummy config file path (contents unused thanks to mocker.patch)
    cfg_path = tmp_path / 'repolish.yaml'
    cfg_path.write_text('')

    # fake resolved configuration object
    fake_config = SimpleNamespace(
        providers_order=['missing'],
        providers={},
        directories=['/extra/dir'],
        template_overrides={'foo': 'bar'},
        no_cookiecutter=False,
        provider_scoped_template_context=False,
        context={},
        context_overrides={},
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
        'repolish.commands.apply.create_cookiecutter_template',
        fake_create,
    )

    # stub out remainder of the pipeline so command completes successfully
    mocker.patch(
        'repolish.commands.apply.build_final_providers',
    ).return_value = SimpleNamespace(
        context={},
        delete_files=[],
        delete_history={},
        create_only_files=[],
        file_mappings={},
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

    # verify branch behaviour: missing provider skipped, extra directory appended
    assert recorded['template_dirs'] == [(None, Path('/extra/dir'))]
    assert recorded['overrides'] == {'foo': 'bar'}
