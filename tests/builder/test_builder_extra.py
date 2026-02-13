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
