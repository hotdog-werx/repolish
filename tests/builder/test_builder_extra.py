from pathlib import Path

from repolish.builder import create_cookiecutter_template


def test_create_cookiecutter_template_handles_missing_repolish(
    tmp_path: Path,
) -> None:
    # Template dir without a repolish/ subdir should not raise and staging
    # should be created (empty)
    template = tmp_path / 'tpl'
    template.mkdir()
    staging = tmp_path / 'staging'

    staging_path = create_cookiecutter_template(staging, [template])
    assert staging_path.exists()
    # no repolish project copied
    assert not (staging / '{{cookiecutter._repolish_project}}').exists()


def test_copy_template_dir_handles_directories(tmp_path: Path) -> None:
    # Create a template that contains a nested directory under repolish/
    template = tmp_path / 'tpl'
    rep = template / 'repolish' / 'subdir'
    rep.mkdir(parents=True, exist_ok=True)
    # add a file inside the nested dir so rglob will traverse it
    (rep / 'nested.txt').write_text('hello')

    staging = tmp_path / 'staging'
    create_cookiecutter_template(staging, [template])

    copied_dir = staging / '{{cookiecutter._repolish_project}}' / 'subdir'
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
    create_cookiecutter_template(staging, [template])

    project_dir = staging / '{{cookiecutter._repolish_project}}'

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


def test_create_cookiecutter_template_with_overrides(tmp_path: Path) -> None:
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
    create_cookiecutter_template(
        staging,
        [('p1', p1), ('p2', p2)],
    )
    project = staging / '{{cookiecutter._repolish_project}}'
    assert (project / 'common.txt').read_text() == 'from p2'

    # with an override pinning the common file to p1
    staging2 = tmp_path / 'staging2'
    create_cookiecutter_template(
        staging2,
        [('p1', p1), ('p2', p2)],
        template_overrides={'common.txt': 'p1'},
    )
    project2 = staging2 / '{{cookiecutter._repolish_project}}'
    assert (project2 / 'common.txt').read_text() == 'from p1'
    # other files unaffected
    assert (project2 / 'unique1.txt').read_text() == 'only p1'
    assert (project2 / 'unique2.txt').read_text() == 'only p2'
