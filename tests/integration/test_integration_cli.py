import json
import textwrap
from pathlib import Path
from pathlib import Path as _Path
from typing import TYPE_CHECKING

from repolish.commands.apply import command as run_repolish
from repolish.config import load_config
from repolish.cookiecutter import build_final_providers, check_generated_output
from repolish.loader import Action

if TYPE_CHECKING:
    import pytest


def write_file(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding='utf-8')


def make_template(
    base: Path,
    name: str,
    repo_name_var: str = 'repolish',
) -> Path:
    tpl_dir = base / name
    # cookiecutter root contains a directory with the repo name
    repo_dir = tpl_dir / repo_name_var
    (repo_dir).mkdir(parents=True, exist_ok=True)
    # file_a.md with an anchor
    write_file(
        repo_dir / 'file_a.md',
        textwrap.dedent("""\
        ## repolish-start[readme]
        Default readme
        repolish-end[readme]
        """),
    )
    # file_b.toml with a regex placeholder line we will preserve
    write_file(
        repo_dir / 'file_b.toml',
        textwrap.dedent("""\
        key = "value"
        ## repolish-regex[keep]: ^important=.*
        """),
    )
    # repolish.py provider that contributes context and deletion
    repolish_py = tpl_dir / 'repolish.py'
    repolish_py.write_text(
        textwrap.dedent("""\
        def create_context():
            return {'repo_name': 'test_repo'}

        def create_delete_files():
            return ['test_repo/file_c']
        """),
        encoding='utf-8',
    )
    return tpl_dir


def test_integration_cli(
    tmp_path: Path,
    monkeypatch: 'pytest.MonkeyPatch',
) -> None:
    # create two template dirs under tmp_path/templates
    templates = tmp_path / 'templates'
    t1 = templates / 'template_a'
    t2 = templates / 'template_b'
    make_template(templates, 'template_a')
    make_template(templates, 'template_b')

    # create project dir with a file that should be used as local override
    project = tmp_path / 'test_repo'
    write_file(
        project / 'file_a.md',
        textwrap.dedent("""\
    Local override content
    """),
    )
    write_file(
        project / 'file_c',
        textwrap.dedent("""\
    to be deleted
    """),
    )

    # write a config file pointing to the two templates; paths should be POSIX
    cfg = tmp_path / 'repolish.yaml'
    cfg.write_text(
        json.dumps(
            {
                'directories': [str((t1).as_posix()), str((t2).as_posix())],
                'context': {},
                'context_overrides': {'repo_name': 'overridden_repo_name'},
                'anchors': {},
                'delete_files': [],
            },
        ),
        encoding='utf-8',
    )

    # run the CLI in check mode with the config path; run() expects argv-like list
    # change working directory to tmp_path so the CLI compares generated files
    # against the project files we created under tmp_path/test_repo
    monkeypatch.chdir(tmp_path)
    rv = run_repolish(cfg, check_only=True)
    # run should return 2 when differences are found (we expect diffs)
    assert rv == 2

    # Recompute providers from the config file used by the run
    cfg_obj = load_config(cfg)
    providers = build_final_providers(cfg_obj)

    # setup_output path next to config file
    base_dir = cfg.resolve().parent
    setup_output = base_dir / '.repolish' / 'setup-output'

    diffs = check_generated_output(setup_output, providers, tmp_path)

    # assert deletion reported for test_repo/file_c

    assert any(
        _Path(rel).as_posix() == 'test_repo/file_c' and msg == 'PRESENT_BUT_SHOULD_BE_DELETED' for rel, msg in diffs
    )

    # check provenance: providers.delete_history should have entries for 'test_repo/file_c'
    hist = providers.delete_history.get('test_repo/file_c')
    assert hist is not None
    assert len(hist) >= 1
    last = hist[-1]
    assert last.action == Action.delete


PRESERVES_CUSTOM_BLOCK_TPL = r"""
name: ci-checks

on: [push]

jobs:
    run-checks:
    runs-on: ubuntu-latest

## repolish-regex[additional-jobs]: ^## post-check-jobs([\s\S]*)$
## post-check-jobs
"""
PRESERVES_CUSTOM_BLOCK_PROJECT = """
name: ci-checks

jobs:
    run-checks:
        runs-on: ubuntu-latest

## post-check-jobs
## Custom job 1
    steps:
        - run: echo "Job 1"
"""


def test_integration_regex_preserves_custom_block(
    tmp_path: Path,
    monkeypatch: 'pytest.MonkeyPatch',
) -> None:
    """Full integration test: regex processors should preserve custom blocks.

    This creates a template containing a repolish-regex marker and a project
    file that already contains custom jobs. Running the CLI should merge
    the custom jobs into the generated template before applying.
    """
    # create a template dir
    templates = tmp_path / 'templates'
    tpl = make_template(templates, 'template_regex')

    # create a conditional CI checks template file with the repolish-regex marker
    tpl_repolish = tpl / 'repolish'
    wf_dir = tpl_repolish / '.github' / 'workflows'
    wf_dir.mkdir(parents=True, exist_ok=True)
    # conditional source file prefixed with _repolish.
    ci_template = wf_dir / '_repolish.ci-checks.yaml'
    ci_template.write_text(PRESERVES_CUSTOM_BLOCK_TPL, encoding='utf-8')

    # ensure the provider declares the file mapping so the conditional file
    # is copied to .github/workflows/ci-checks.yaml when applied
    (tpl / 'repolish.py').write_text(
        textwrap.dedent("""\
        def create_context():
            return {'repo_name': 'repolish'}

        def create_file_mappings():
            return {
                '.github/workflows/ci-checks.yaml': '.github/workflows/_repolish.ci-checks.yaml'
            }
        """),
        encoding='utf-8',
    )

    # create project file with custom jobs that should be preserved
    # The CLI uses the config file's parent as the base_dir, so create
    # the project file directly under tmp_path (the config parent).
    project = tmp_path
    write_file(
        project / '.github' / 'workflows' / 'ci-checks.yaml',
        PRESERVES_CUSTOM_BLOCK_PROJECT,
    )

    # write config pointing to the template
    cfg = project / 'repolish.yaml'
    cfg.write_text(
        json.dumps(
            {
                'directories': [str((tpl).as_posix())],
                'context': {},
                'anchors': {},
                'delete_files': [],
            },
        ),
        encoding='utf-8',
    )

    # run the CLI to apply changes (not check mode)
    monkeypatch.chdir(project)
    rv = run_repolish(cfg, check_only=False)
    assert rv == 0

    # verify the project file now contains the custom job preserved
    dest_file = project / '.github' / 'workflows' / 'ci-checks.yaml'
    result = dest_file.read_text()
    assert '## Custom job 1' in result

    # The conditional source file itself should NOT have been copied
    src_copy = project / '.github' / 'workflows' / '_repolish.ci-checks.yaml'
    assert not src_copy.exists()


def test_integration_context_provider_uses_config_and_merges(
    tmp_path: Path,
    monkeypatch: 'pytest.MonkeyPatch',
) -> None:
    """Providers can read config values and derive additional context.

    Config provides `my_var: 'a'`. The provider's `create_context` will read
    `my_var`, attempt to override it with 'A' (which should lose to config),
    and set `my_collection` to `my_var + 'b'` resulting in 'ab'. We assert the
    generated cookiecutter.json in the setup-output contains the final merged
    values.
    """
    # create a template dir
    templates = tmp_path / 'templates'
    tpl = make_template(templates, 'template_ctx')

    # provider that attempts to override my_var and derives my_collection
    (tpl / 'repolish.py').write_text(
        textwrap.dedent("""\
        def create_context(ctx=None):
            # try to read my_var from incoming context
            incoming = (ctx or {}).get('my_var')
            # attempt to override my_var to 'A' (should be trumped by config)
            # and set my_collection based on incoming value
            return {'my_var': 'A', 'my_collection': f"{incoming}b"}
        """),
        encoding='utf-8',
    )

    # write config pointing to the template and seed context my_var: 'a'
    cfg = tmp_path / 'repolish.yaml'
    cfg.write_text(
        json.dumps(
            {
                'directories': [str((tpl).as_posix())],
                'context': {'my_var': 'a'},
                'anchors': {},
                'delete_files': [],
            },
        ),
        encoding='utf-8',
    )

    # run the CLI to build setup-output (not check mode)
    monkeypatch.chdir(tmp_path)
    rv = run_repolish(cfg, check_only=False)
    assert rv == 0

    # load the setup-input cookiecutter.json produced by the build
    setup_input = (cfg.resolve().parent) / '.repolish' / 'setup-input'
    cookie_path = setup_input / 'cookiecutter.json'
    assert cookie_path.exists(), 'cookiecutter.json not generated in setup-input'

    data = json.loads(cookie_path.read_text(encoding='utf-8'))
    # config value should be authoritative
    assert data.get('my_var') == 'a'
    # derived value should reflect the merged input (my_var from config)
    assert data.get('my_collection') == 'ab'
