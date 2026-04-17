from pathlib import Path

from repolish.builder import stage_templates


def test_stage_templates_handles_missing_repolish(
    tmp_path: Path,
) -> None:
    # Template dir without a repolish/ subdir should not raise and staging
    # should be created (empty)
    template = tmp_path / 'tpl'
    template.mkdir()
    staging = tmp_path / 'staging'

    staging_path, _ = stage_templates(staging, [template])
    assert staging_path.exists()
    # no repolish project files copied — staging/repolish dir should not exist
    assert not (staging_path / 'repolish').exists()


def test_copy_template_dir_handles_directories(tmp_path: Path) -> None:
    # Create a template that contains a nested directory under repolish/
    template = tmp_path / 'tpl'
    rep = template / 'repolish' / 'subdir'
    rep.mkdir(parents=True, exist_ok=True)
    # add a file inside the nested dir so rglob will traverse it
    (rep / 'nested.txt').write_text('hello')

    staging = tmp_path / 'staging'
    _, _ = stage_templates(staging, [template])

    copied_dir = staging / 'repolish' / 'subdir'
    assert copied_dir.exists()
    assert copied_dir.is_dir()


def test_jinja_extension_stripped_from_filenames(tmp_path: Path) -> None:
    # Files with .jinja extension should have it stripped when copied
    template = tmp_path / 'tpl'
    rep = template / 'repolish'
    rep.mkdir(parents=True, exist_ok=True)

    # Create various test files
    (rep / 'config.yaml.jinja').write_text('key: value')
    (rep / 'template.html.jinja').write_text('<html></html>')
    (rep / 'actual.jinja.jinja').write_text('double jinja')
    (rep / 'regular.txt').write_text('no jinja')

    staging = tmp_path / 'staging'
    _, _ = stage_templates(staging, [template])

    project_dir = staging / 'repolish'

    # .jinja extension should be stripped
    assert (project_dir / 'config.yaml').exists()
    assert not (project_dir / 'config.yaml.jinja').exists()

    assert (project_dir / 'template.html').exists()
    assert not (project_dir / 'template.html.jinja').exists()

    # Double .jinja should strip one .jinja
    assert (project_dir / 'actual.jinja').exists()
    assert not (project_dir / 'actual.jinja.jinja').exists()

    # Regular files should remain unchanged
    assert (project_dir / 'regular.txt').exists()


def test_stage_templates_with_overrides(tmp_path: Path) -> None:
    """Provider-specific overrides prevent later provider from overwriting a file pinned to an earlier provider."""
    # provider1 defines a common file and a unique file
    p1 = tmp_path / 'p1'
    rep1 = p1 / 'repolish'
    rep1.mkdir(parents=True)
    (rep1 / 'common.txt').write_text('from p1')
    (rep1 / 'unique1.txt').write_text('only p1')

    # provider2 defines the same common file and its own unique file
    p2 = tmp_path / 'p2'
    rep2 = p2 / 'repolish'
    rep2.mkdir(parents=True)
    (rep2 / 'common.txt').write_text('from p2')
    (rep2 / 'unique2.txt').write_text('only p2')

    staging = tmp_path / 'staging'

    # without overrides, later provider wins
    _, _ = stage_templates(
        staging,
        [('p1', p1), ('p2', p2)],
    )
    project = staging / 'repolish'
    assert (project / 'common.txt').read_text() == 'from p2'

    # with an override pinning the common file to p1
    staging2 = tmp_path / 'staging2'
    _, _ = stage_templates(
        staging2,
        [('p1', p1), ('p2', p2)],
        template_overrides={'common.txt': 'p1'},
    )
    project2 = staging2 / 'repolish'
    assert (project2 / 'common.txt').read_text() == 'from p1'
    # other files unaffected
    assert (project2 / 'unique1.txt').read_text() == 'only p1'
    assert (project2 / 'unique2.txt').read_text() == 'only p2'

    # with a None override, the file is suppressed entirely — absent from every provider
    staging3 = tmp_path / 'staging3'
    _, sources3 = stage_templates(
        staging3,
        [('p1', p1), ('p2', p2)],
        template_overrides={'common.txt': None},
    )
    project3 = staging3 / 'repolish'
    assert not (project3 / 'common.txt').exists()
    assert 'common.txt' not in sources3
    # unique files from both providers are still present
    assert (project3 / 'unique1.txt').exists()
    assert (project3 / 'unique2.txt').exists()


def test_template_sources_are_posix_ids(tmp_path: Path) -> None:
    """Returned sources map should normalise provider IDs to forward slashes.

    On Windows the fallback behaviour previously returned raw `str(Path)`
    values which contain backslashes.  When those values were later used as
    keys against the loader's provider maps the lookup failed and `None`
    migrated flags were logged.  Normalising here avoids that mismatch.
    """
    p = tmp_path / 'prov'
    (p / 'repolish').mkdir(parents=True)
    (p / 'repolish' / 'foo.txt').write_text('bar')

    staging = tmp_path / 'staging'
    # provide an explicit alias containing backslashes to mimic a Windows path
    alias = 'C:\\windows\\path'
    _, sources = stage_templates(staging, [(alias, p)])

    # every provider id in the returned map should be POSIX-formatted
    for v in sources.values():
        assert '\\' not in v
        assert '/' in v  # simple sanity check
    # the alias should have been normalised (slashes flipped)
    assert next(iter(sources.values())) == alias.replace('\\', '/')


def test_mapped_sources_stages_and_registers_templates(
    tmp_path: Path,
) -> None:
    """Files in mapped_sources (claimed by create_file_mappings) are staged and registered.

    A provider that explicitly maps 'workflows/ci.yaml' in create_file_mappings
    needs the file present in setup_output so the renderer can find the template,
    and it must appear in sources so the renderer can look up the declaring
    provider's context (enabling {{ _provider }} access in the template).

    The file-records display layer (build_file_records) is responsible for
    filtering these staging intermediates out so they don't appear as managed
    output files.
    """
    tpl = tmp_path / 'prov'
    rep = tpl / 'repolish'
    rep.mkdir(parents=True)
    (rep / 'workflows').mkdir()
    (rep / 'workflows' / 'ci.yaml.jinja').write_text('ci: {{ var }}')
    (rep / 'README.md').write_text('readme')

    staging = tmp_path / 'staging'
    # workflows/ci.yaml is claimed by a file mapping — include it as a mapped source
    _, sources = stage_templates(
        staging,
        [tpl],
        mapped_sources={'workflows/ci.yaml'},
    )

    staged = staging / 'repolish'
    # README was not excluded — should be staged and registered normally
    assert (staged / 'README.md').exists()
    assert 'README.md' in sources
    # ci.yaml was excluded — file IS staged AND registered in sources so the
    # renderer can look up the declaring provider's context
    assert (staged / 'workflows' / 'ci.yaml').exists()
    assert 'workflows/ci.yaml' in sources


def test_stage_templates_mode_overlay(tmp_path: Path) -> None:
    """Mode-specific overlay directories are staged after the base repolish/ dir.

    Files in provider_root/{mode}/ are staged with the same provider alias and
    override any collisions from the base repolish/ directory.  Files only in
    repolish/ that are absent from the mode directory are unaffected.
    """
    prov = tmp_path / 'p'
    # Base templates — mode-agnostic
    rep = prov / 'repolish'
    rep.mkdir(parents=True)
    (rep / 'shared.txt').write_text('base shared')
    (rep / 'base_only.txt').write_text('base only')

    # root-mode overlay: overrides shared.txt, adds root_only.txt
    root_dir = prov / 'root'
    root_dir.mkdir()
    (root_dir / 'shared.txt').write_text('root override')
    (root_dir / 'root_only.txt').write_text('root only')

    # member-mode overlay: only adds member_only.txt
    member_dir = prov / 'member'
    member_dir.mkdir()
    (member_dir / 'member_only.txt').write_text('member only')

    staging_root = tmp_path / 'staging_root'
    _, sources_root = stage_templates(
        staging_root,
        [('p', prov)],
        workspace_mode='root',
    )
    proj_root = staging_root / 'repolish'
    # overlay overrides the base version
    assert (proj_root / 'shared.txt').read_text() == 'root override'
    # overlay files carry the annotated alias so callers can track the origin dir
    assert sources_root['shared.txt'] == 'p:root'
    assert sources_root['base_only.txt'] == 'p'
    # base-only file is unaffected
    assert (proj_root / 'base_only.txt').read_text() == 'base only'
    # root-specific file is present
    assert (proj_root / 'root_only.txt').read_text() == 'root only'
    # member-only file is absent when mode is root
    assert not (proj_root / 'member_only.txt').exists()

    staging_member = tmp_path / 'staging_member'
    _, _ = stage_templates(
        staging_member,
        [('p', prov)],
        workspace_mode='member',
    )
    proj_member = staging_member / 'repolish'
    # base version is kept (no member override for shared.txt)
    assert (proj_member / 'shared.txt').read_text() == 'base shared'
    assert (proj_member / 'member_only.txt').read_text() == 'member only'
    # root-only file is absent when mode is member
    assert not (proj_member / 'root_only.txt').exists()

    # Without workspace_mode, no overlay is applied
    staging_none = tmp_path / 'staging_none'
    _, _ = stage_templates(staging_none, [('p', prov)])
    proj_none = staging_none / 'repolish'
    assert (proj_none / 'shared.txt').read_text() == 'base shared'
    assert not (proj_none / 'root_only.txt').exists()
    assert not (proj_none / 'member_only.txt').exists()


def test_stage_templates_mode_overlay_skips_overridden_file(
    tmp_path: Path,
) -> None:
    """template_overrides suppress files in mode overlay dirs (builder.py line 241)."""
    prov = tmp_path / 'p'
    (prov / 'repolish').mkdir(parents=True)
    (prov / 'repolish' / 'base.txt').write_text('base')
    root_dir = prov / 'root'
    root_dir.mkdir()
    (root_dir / 'secret.txt').write_text('should be suppressed')

    staging = tmp_path / 'staging'
    _, sources = stage_templates(
        staging,
        [('p', prov)],
        workspace_mode='root',
        # suppress 'secret.txt' from all providers (None value = suppress)
        template_overrides={'secret.txt': None},
    )
    # The suppressed file must not appear in staging
    assert not (staging / 'repolish' / 'secret.txt').exists()
    assert 'secret.txt' not in sources


def test_stage_templates_mode_overlay_skips_unmapped_conditional(
    tmp_path: Path,
) -> None:
    """Conditional files not in mapped_sources are skipped in overlay dirs (builder.py line 249)."""
    prov = tmp_path / 'p'
    (prov / 'repolish').mkdir(parents=True)
    (prov / 'repolish' / 'base.txt').write_text('base')
    root_dir = prov / 'root'
    root_dir.mkdir()
    # Conditional file: starts with _repolish.
    (root_dir / '_repolish.ci.toml').write_text('[ci]')
    # Regular file: always staged
    (root_dir / 'regular.txt').write_text('regular')

    staging = tmp_path / 'staging'
    _, _sources = stage_templates(
        staging,
        [('p', prov)],
        workspace_mode='root',
        # mapped_sources does NOT include '_repolish.ci.toml'
        mapped_sources=set(),
    )
    # Unmapped conditional file must be absent
    assert not (staging / 'repolish' / '_repolish.ci.toml').exists()
    # Regular file is staged normally
    assert (staging / 'repolish' / 'regular.txt').exists()
