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


def test_excluded_sources_skips_explicitly_mapped_templates(
    tmp_path: Path,
) -> None:
    """Files listed in excluded_sources are staged AND registered in sources.

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
    # exclude the workflows/ci.yaml source — it is claimed by a file mapping
    _, sources = stage_templates(
        staging,
        [tpl],
        excluded_sources={'workflows/ci.yaml'},
    )

    staged = staging / 'repolish'
    # README was not excluded — should be staged and registered normally
    assert (staged / 'README.md').exists()
    assert 'README.md' in sources
    # ci.yaml was excluded — file IS staged AND registered in sources so the
    # renderer can look up the declaring provider's context
    assert (staged / 'workflows' / 'ci.yaml').exists()
    assert 'workflows/ci.yaml' in sources
