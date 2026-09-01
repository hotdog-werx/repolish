"""Tests for hydration staging functionality."""

import sys
import textwrap
from pathlib import Path

import pytest
from pydantic import BaseModel

from repolish.builder import stage_templates
from repolish.hydration.staging import preprocess_templates
from repolish.providers import SessionBundle, TemplateMapping
from repolish.providers.models.files import FileMode


def write_file(p: Path, content: str) -> None:
    """Helper to write a file with proper encoding."""
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding='utf-8')


def make_template_with_unreadable(base: Path, name: str) -> None:
    """Create a template with an unreadable file for testing."""
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


def test_unreadable_template_file_skipped(tmp_path: Path) -> None:
    """Test that unreadable template files are skipped during preprocessing."""
    # Create a template with a readable secret file
    templates = tmp_path / 'templates'
    make_template_with_unreadable(templates, 'template_a')
    t1 = templates / 'template_a'

    # Stage the template into setup_input using the builder helper
    staging = tmp_path / '.repolish'
    setup_input = staging / '_' / 'stage'
    _, _ = stage_templates(setup_input, [t1])

    # Find the staged secret file and make it unreadable
    staged_secret = setup_input / 'repolish' / 'secret.txt'
    assert staged_secret.exists()
    staged_secret.chmod(0)

    # Prepare a minimal providers object for preprocessing
    providers = SessionBundle(
        anchors={},
        delete_files=[],
        delete_history={},
    )

    # Call preprocess_templates directly; it should skip the unreadable file and not raise
    preprocess_templates(
        setup_input,
        providers,
        tmp_path,
    )


def test_preprocess_templates_writes_file_when_anchor_content_changes(
    tmp_path: Path,
) -> None:
    """preprocess_templates rewrites the staged file when anchor content differs.

    Exercises the `tpl.write_text(new_text, ...)` branch (staging.py line 65)
    which is only reached when replace_text returns text different from the
    original template content.
    """
    setup_input = tmp_path / '_' / 'stage'
    tpl_dir = setup_input / 'repolish'
    tpl_dir.mkdir(parents=True)

    # Template file has anchor with default placeholder content
    tpl_file = tpl_dir / 'README.md'
    tpl_file.write_text(
        '## repolish-start[intro]\nDefault content\nrepolish-end[intro]\n',
        encoding='utf-8',
    )

    # Local project file has different content inside the same anchor
    base_dir = tmp_path / 'project'
    base_dir.mkdir()
    (base_dir / 'README.md').write_text(
        '## repolish-start[intro]\nProject-specific content\nrepolish-end[intro]\n',
        encoding='utf-8',
    )

    providers = SessionBundle(
        anchors={},
        delete_files=[],
        delete_history={},
    )

    preprocess_templates(setup_input, providers, base_dir)

    # anchor markers are control syntax stripped from the output; the file
    # should differ from the original staged content
    updated = tpl_file.read_text(encoding='utf-8')
    original = '## repolish-start[intro]\nDefault content\nrepolish-end[intro]\n'
    assert updated != original
    assert 'repolish-start' not in updated


@pytest.mark.skipif(
    sys.platform == 'win32',
    reason='Windows does not support Unix executable bits',
)
def test_preprocess_templates_preserves_executable_bit(tmp_path: Path) -> None:
    """The executable bit on a staged script is preserved after anchor preprocessing."""
    setup_input = tmp_path / '_' / 'stage'
    tpl_dir = setup_input / 'repolish'
    tpl_dir.mkdir(parents=True)

    # Staged script with an anchor block and executable bit
    script = tpl_dir / 'run.sh'
    script.write_text(
        '#!/bin/bash\n## repolish-start[body]\necho default\nrepolish-end[body]\n',
        encoding='utf-8',
    )
    script.chmod(0o755)

    # Local project file has different anchor content (triggers the write_text branch)
    base_dir = tmp_path / 'project'
    base_dir.mkdir()
    (base_dir / 'run.sh').write_text(
        '#!/bin/bash\n## repolish-start[body]\necho custom\nrepolish-end[body]\n',
        encoding='utf-8',
    )

    providers = SessionBundle(anchors={}, delete_files=[], delete_history={})
    preprocess_templates(setup_input, providers, base_dir)

    assert script.stat().st_mode & 0o111, 'executable bit must be preserved after anchor preprocessing'


def test_preprocess_templates_uses_promoted_file_mappings_for_regex_lookup(
    tmp_path: Path,
) -> None:
    """Regression: promoted mappings should participate in local-content lookup.

    A promoted template source must map to its destination path before
    preprocessing so regex directives can capture values from the existing file
    on disk. Without that mapping, preprocessing falls back to an unrelated
    local path and leaves template defaults unchanged.
    """
    setup_input = tmp_path / '_' / 'stage'
    tpl_dir = setup_input / 'repolish'
    tpl_dir.mkdir(parents=True)

    # Staged template source (promoted mapping source) with regex preserve rule.
    promoted_source = tpl_dir / '_repolish._ci-checks.yaml'
    promoted_source.write_text(
        textwrap.dedent(
            """\
            ## repolish-regex[member]: member:\\s*(.+)
            member: default-member
            """,
        ),
        encoding='utf-8',
    )

    # Existing destination file in project root where promoted mapping points.
    base_dir = tmp_path / 'project'
    base_dir.mkdir()
    promoted_dest = base_dir / '.github' / 'workflows' / '_ci-checks_pkg-alpha.yaml'
    promoted_dest.parent.mkdir(parents=True, exist_ok=True)
    promoted_dest.write_text('member: pkg-alpha\n', encoding='utf-8')

    providers = SessionBundle(
        anchors={},
        delete_files=[],
        delete_history={},
        promoted_file_mappings={
            '.github/workflows/_ci-checks_pkg-alpha.yaml': '_repolish._ci-checks.yaml',
        },
    )

    preprocess_templates(setup_input, providers, base_dir)

    updated = promoted_source.read_text(encoding='utf-8')
    assert 'member: pkg-alpha' in updated
    assert 'repolish-regex' not in updated


# ---------------------------------------------------------------------------
# Tests: unmapped _repolish.* files are excluded from the staging tree
# ---------------------------------------------------------------------------


def _make_provider_dir(base: Path, files: list[str]) -> Path:
    """Create a provider dir with the given files under repolish/."""
    provider = base / 'provider'
    (provider / 'repolish').mkdir(parents=True)
    for name in files:
        p = provider / 'repolish' / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('content', encoding='utf-8')
    return provider


def test_unmapped_conditional_file_not_staged(tmp_path: Path) -> None:
    """_repolish.* files that are not in mapped_sources must not be staged."""
    provider = _make_provider_dir(
        tmp_path,
        ['README.md', '_repolish.variant-a.md', '_repolish.variant-b.md'],
    )
    staging = tmp_path / 'stage'
    _, _sources = stage_templates(staging, [provider], mapped_sources=set())

    staged = {p.name for p in (staging / 'repolish').rglob('*') if p.is_file()}
    assert 'README.md' in staged
    assert '_repolish.variant-a.md' not in staged
    assert '_repolish.variant-b.md' not in staged


def test_mapped_conditional_file_is_staged(tmp_path: Path) -> None:
    """_repolish.* files that ARE in mapped_sources must be staged."""
    provider = _make_provider_dir(
        tmp_path,
        ['README.md', '_repolish.variant-a.md', '_repolish.variant-b.md'],
    )
    staging = tmp_path / 'stage'
    # only variant-a is mapped
    _, _sources = stage_templates(
        staging,
        [provider],
        mapped_sources={'_repolish.variant-a.md'},
    )

    staged = {p.name for p in (staging / 'repolish').rglob('*') if p.is_file()}
    assert 'README.md' in staged
    assert '_repolish.variant-a.md' in staged
    assert '_repolish.variant-b.md' not in staged


def test_conditional_files_staged_when_mapped_sources_is_none(
    tmp_path: Path,
) -> None:
    """When mapped_sources is omitted (None) the skip logic does not apply."""
    provider = _make_provider_dir(
        tmp_path,
        ['README.md', '_repolish.variant-a.md'],
    )
    staging = tmp_path / 'stage'
    _, _sources = stage_templates(staging, [provider])  # mapped_sources=None

    staged = {p.name for p in (staging / 'repolish').rglob('*') if p.is_file()}
    assert 'README.md' in staged
    assert '_repolish.variant-a.md' in staged


def test_unmapped_conditional_folder_not_staged(tmp_path: Path) -> None:
    """Files inside a _repolish. folder not in mapped_sources must not be staged."""
    provider = _make_provider_dir(
        tmp_path,
        ['README.md', '_repolish.ci.github/workflows/ci.yml'],
    )
    staging = tmp_path / 'stage'
    _, _sources = stage_templates(staging, [provider], mapped_sources=set())

    staged = {p.relative_to(staging / 'repolish').as_posix() for p in (staging / 'repolish').rglob('*') if p.is_file()}
    assert 'README.md' in staged
    assert '_repolish.ci.github/workflows/ci.yml' not in staged


def test_mapped_conditional_folder_file_is_staged(tmp_path: Path) -> None:
    """Files inside a _repolish. folder that ARE in mapped_sources must be staged."""
    provider = _make_provider_dir(
        tmp_path,
        [
            'README.md',
            '_repolish.ci.github/workflows/ci.yml',
            '_repolish.ci.gitlab/ci.yml',
        ],
    )
    staging = tmp_path / 'stage'
    _, _sources = stage_templates(
        staging,
        [provider],
        mapped_sources={'_repolish.ci.github/workflows/ci.yml'},
    )

    staged = {p.relative_to(staging / 'repolish').as_posix() for p in (staging / 'repolish').rglob('*') if p.is_file()}
    assert 'README.md' in staged
    assert '_repolish.ci.github/workflows/ci.yml' in staged
    assert '_repolish.ci.gitlab/ci.yml' not in staged


def test_preprocess_one_template_to_multiple_destinations_with_keep_blocks(
    tmp_path: Path,
) -> None:
    """Test keep-blocks are preserved per-destination for multi-destination mappings.

    This is the core issue that prompted the fix: a template with keep-blocks
    (e.g., repolish-keep-block) should extract different content from dev.toml
    vs prod.toml when they have different developer modifications.

    Before the fix, only one destination's keep-blocks would be preserved,
    killing developer content in the other files.
    """
    setup_input = tmp_path / '_' / 'stage'
    tpl_dir = setup_input / 'repolish'
    tpl_dir.mkdir(parents=True)

    # Single template with a keep-block region that developers can modify
    tpl = tpl_dir / 'config.toml.jinja'
    tpl.write_text(
        textwrap.dedent("""\
        # Config file
        ## repolish-keep-block[custom]: start="## CUSTOM_START" end="## CUSTOM_END"
        default_section:
          key: default_value
        ## CUSTOM_START
        # developer custom content here
        ## CUSTOM_END
        another_section: true
        """),
        encoding='utf-8',
    )

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # dev.toml has developer's custom content for dev environment
    (base_dir / 'dev.toml').write_text(
        textwrap.dedent("""\
        # Dev config
        ## CUSTOM_START
        dev_specific:
          debug: true
          log_level: verbose
        ## CUSTOM_END
        """),
        encoding='utf-8',
    )

    # prod.toml has developer's custom content for prod environment
    (base_dir / 'prod.toml').write_text(
        textwrap.dedent("""\
        # Prod config
        ## CUSTOM_START
        prod_specific:
          debug: false
          log_level: error
        ## CUSTOM_END
        """),
        encoding='utf-8',
    )

    class Ctx(BaseModel):
        env_name: str

    providers = SessionBundle(
        anchors={},
        file_mappings={
            'dev.toml': TemplateMapping(
                'config.toml.jinja',
                extra_context=Ctx(env_name='development'),
            ),
            'prod.toml': TemplateMapping(
                'config.toml.jinja',
                extra_context=Ctx(env_name='production'),
            ),
        },
    )

    preprocess_templates(setup_input, providers, base_dir)

    # The original template should still exist (for provenance)
    assert tpl.exists(), 'Original template should remain'

    # Preprocessed copies should exist with destination-encoded names
    preproc_dev = tpl_dir / '_preproc_dev.toml_config.toml.jinja'
    preproc_prod = tpl_dir / '_preproc_prod.toml_config.toml.jinja'

    assert preproc_dev.exists(), f'Preprocessed dev copy should exist. Files: {list(tpl_dir.iterdir())}'
    assert preproc_prod.exists(), f'Preprocessed prod copy should exist. Files: {list(tpl_dir.iterdir())}'

    # Each preprocessed copy should have the correct keep-block content extracted
    dev_content = preproc_dev.read_text()
    prod_content = preproc_prod.read_text()

    # Dev should have dev-specific keep-block content
    assert 'dev_specific:' in dev_content, f'Dev should have dev-specific content: {dev_content}'
    assert 'debug: true' in dev_content, f'Dev should have debug: true: {dev_content}'
    assert 'log_level: verbose' in dev_content, f'Dev should have log_level: verbose: {dev_content}'

    # Prod should have prod-specific keep-block content
    assert 'prod_specific:' in prod_content, f'Prod should have prod-specific content: {prod_content}'
    assert 'debug: false' in prod_content, f'Prod should have debug: false: {prod_content}'
    assert 'log_level: error' in prod_content, f'Prod should have log_level: error: {prod_content}'

    # Neither should have the keep-block directive itself (it gets applied and stripped)
    assert 'repolish-keep-block' not in dev_content
    assert 'repolish-keep-block' not in prod_content

    # Both should still have the non-keep-block parts of the template
    assert 'default_section:' in dev_content
    assert 'default_section:' in prod_content
    assert 'another_section: true' in dev_content
    assert 'another_section: true' in prod_content

    # Mappings should point to preprocessed copies but preserve original source_template
    dev_mapping = providers.file_mappings['dev.toml']
    prod_mapping = providers.file_mappings['prod.toml']

    # Type narrowing: we know these are TemplateMapping entries
    assert isinstance(dev_mapping, TemplateMapping)
    assert isinstance(prod_mapping, TemplateMapping)

    assert dev_mapping.source_template == 'config.toml.jinja', 'source_template should be preserved'
    assert prod_mapping.source_template == 'config.toml.jinja', 'source_template should be preserved'
    assert dev_mapping.preprocessed_source == '_preproc_dev.toml_config.toml.jinja'
    assert prod_mapping.preprocessed_source == '_preproc_prod.toml_config.toml.jinja'


def test_preprocess_templates_skips_suppress_mode_mappings(
    tmp_path: Path,
) -> None:
    """Test that TemplateMapping with file_mode=SUPPRESS is skipped during preprocessing.

    This covers the branch at staging.py:94 where suppress mode mappings
    return None from _get_source_template and are not preprocessed.
    """
    setup_input = tmp_path / '_' / 'stage'
    tpl_dir = setup_input / 'repolish'
    tpl_dir.mkdir(parents=True)

    # Template file that would normally be preprocessed
    tpl = tpl_dir / 'suppressed.toml.jinja'
    original_content = (
        '## repolish-keep-block[test]: start="## START" end="## END"\nkey: value\n## START\ntemplate default\n## END\n'
    )
    tpl.write_text(original_content, encoding='utf-8')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # Local file has different keep-block content
    (base_dir / 'suppressed.toml').write_text(
        '## START\nlocal override\n## END\n',
        encoding='utf-8',
    )

    # Mapping with SUPPRESS mode should skip preprocessing entirely
    providers = SessionBundle(
        anchors={},
        file_mappings={
            'suppressed.toml': TemplateMapping(
                source_template='suppressed.toml.jinja',
                file_mode=FileMode.SUPPRESS,
            ),
        },
    )

    preprocess_templates(setup_input, providers, base_dir)

    # Template should remain unchanged (no preprocessing applied)
    updated = tpl.read_text(encoding='utf-8')
    assert updated == original_content, 'SUPPRESS mode should skip preprocessing'

    # Mapping should still point to original template (no preprocessed copy created)
    mapping = providers.file_mappings['suppressed.toml']
    assert isinstance(mapping, TemplateMapping)
    assert mapping.source_template == 'suppressed.toml.jinja'
    assert mapping.preprocessed_source is None


ZONE_TEMPLATE = """\
# Project

## repolish:insert[badges] start="<!-- generated:badges:on" end="<!-- generated:badges:off -->"
<!-- generated:badges:on -->
_default._
<!-- generated:badges:off -->
"""


def test_preprocess_templates_ferries_zone_declarations_relativized(
    tmp_path: Path,
) -> None:
    """Auto-staged zone templates return declarations keyed by project path."""
    setup_input = tmp_path / '_' / 'stage'
    tpl_dir = setup_input / 'repolish'
    tpl_dir.mkdir(parents=True)
    write_file(tpl_dir / 'README.md', ZONE_TEMPLATE)

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    providers = SessionBundle(anchors={}, delete_files=[], delete_history={})

    declarations = preprocess_templates(setup_input, providers, base_dir)

    assert [(d.name, d.dest) for d in declarations] == [('badges', 'README.md')]
    # The directive line was stripped from the staged template; the zone
    # region (markers + template default) flows through untouched.
    staged = (tpl_dir / 'README.md').read_text(encoding='utf-8')
    assert 'repolish:insert' not in staged
    assert '_default._' in staged


def test_preprocess_templates_ferries_mapping_destinations(tmp_path: Path) -> None:
    """A TemplateMapping destination gets its own pre-render declaration."""
    setup_input = tmp_path / '_' / 'stage'
    tpl_dir = setup_input / 'repolish'
    tpl_dir.mkdir(parents=True)
    write_file(tpl_dir / 'README.template.md', ZONE_TEMPLATE)

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    providers = SessionBundle(
        anchors={},
        file_mappings={
            'docs/README.md': TemplateMapping(source_template='README.template.md'),
        },
    )

    declarations = preprocess_templates(setup_input, providers, base_dir)

    assert [(d.name, d.dest) for d in declarations] == [
        ('badges', 'docs/README.md'),
    ]
