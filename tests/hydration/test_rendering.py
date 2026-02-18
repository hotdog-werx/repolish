from pathlib import Path
from textwrap import dedent

import pytest
from jinja2 import TemplateSyntaxError, UndefinedError

from repolish.builder import create_cookiecutter_template
from repolish.config.models import RepolishConfig
from repolish.hydration.rendering import render_template
from repolish.hydration.staging import prepare_staging, preprocess_templates
from repolish.loader.types import Providers


def _make_template_dir(tmp_path: Path, name: str = 'example') -> Path:
    tpl = tmp_path / name
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    # Create a templated directory name + templated file content
    templated_dir = tpl / 'repolish' / '{{cookiecutter.package_name}}'
    templated_dir.mkdir(parents=True, exist_ok=True)
    (templated_dir / 'README.md.jinja').write_text(
        dedent("""
        # {{ cookiecutter.package_name }}

        Description: {{ cookiecutter.description }}
        """),
        encoding='utf-8',
    )
    return tpl


def test_render_template_with_no_cookiecutter_renders_jinja(tmp_path: Path):
    """When config.no_cookiecutter is True, templates are rendered with Jinja2."""
    tpl = _make_template_dir(tmp_path)

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)

    create_cookiecutter_template(setup_input, [tpl])

    providers = Providers(
        context={
            'package_name': 'acme',
            'description': 'Acme project',
            '_repolish_project': 'proj',
        },
    )

    # Preprocess (anchor-driven replacements) - no-op for this template
    preprocess_templates(setup_input, providers, config, base_dir)

    # Render using Jinja (opt-in)
    config.no_cookiecutter = True
    render_template(setup_input, providers, setup_output, config)

    out_file = setup_output / 'proj' / 'acme' / 'README.md'
    assert out_file.exists()
    text = out_file.read_text(encoding='utf-8')
    assert '# acme' in text
    assert 'Description: Acme project' in text


def test_render_with_jinja_exposes_merged_context_top_level(tmp_path: Path):
    """Merged provider context should be available as top-level variables.

    This allows templates to drop the `cookiecutter.` prefix during migration.
    """
    tpl = tmp_path / 'tpl-top-level'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)

    # Use both cookiecutter.package_name and package_name in content and path
    (tpl / 'repolish' / '{{package_name}}').mkdir(parents=True, exist_ok=True)
    (tpl / 'repolish' / '{{package_name}}' / 'README.md.jinja').write_text(
        'name: {{ cookiecutter.package_name }}\nalt: {{ package_name }}\n',
        encoding='utf-8',
    )

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    create_cookiecutter_template(setup_input, [tpl])

    providers = Providers(
        context={'package_name': 'acme', '_repolish_project': 'repolish'},
    )
    preprocess_templates(setup_input, providers, config, base_dir)

    config.no_cookiecutter = True
    render_template(setup_input, providers, setup_output, config)

    out_file = setup_output / 'repolish' / 'acme' / 'README.md'
    assert out_file.exists()
    text = out_file.read_text(encoding='utf-8')
    assert 'name: acme' in text
    assert 'alt: acme' in text


def test_cookiecutter_and_jinja_paths_produce_equivalent_output(tmp_path: Path):
    """Ensure disabling cookiecutter produces equivalent rendered files."""
    tpl = _make_template_dir(tmp_path, name='tpl2')

    config = RepolishConfig(config_dir=tmp_path)

    # --- cookiecutter run (default) ---
    base_dir, setup_input, setup_output = prepare_staging(config)
    create_cookiecutter_template(setup_input, [tpl])
    providers = Providers(
        context={'package_name': 'demo', 'description': 'Demo project'},
    )
    preprocess_templates(setup_input, providers, config, base_dir)

    # run cookiecutter (default behavior)
    render_template(setup_input, providers, setup_output, config)
    cookie_out = setup_output / 'repolish' / 'demo' / 'README.md'
    assert cookie_out.exists()
    cookie_text = cookie_out.read_text(encoding='utf-8')

    # --- jinja run (opted-out) ---
    base_dir, setup_input, setup_output = prepare_staging(config)
    create_cookiecutter_template(setup_input, [tpl])
    preprocess_templates(setup_input, providers, config, base_dir)

    config.no_cookiecutter = True
    # When opting out, provider context needs _repolish_project if you want a specific folder
    providers.context.setdefault('_repolish_project', 'repolish')
    render_template(setup_input, providers, setup_output, config)

    jinja_out = setup_output / 'repolish' / 'demo' / 'README.md'
    assert jinja_out.exists()
    jinja_text = jinja_out.read_text(encoding='utf-8')

    assert cookie_text == jinja_text


def test_render_with_jinja_copies_binary_files(tmp_path: Path):
    """Binary files in templates should be copied unchanged when using Jinja."""
    tpl = tmp_path / 'tpl-bin'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)

    # Text file + binary file in provider template
    (tpl / 'repolish' / 'README.md.jinja').write_text(
        '# example\n',
        encoding='utf-8',
    )
    (tpl / 'repolish' / 'logo.png').write_bytes(
        b'\x89PNG\r\n\x1a\n\x00\x00\x00',
    )

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)

    create_cookiecutter_template(setup_input, [tpl])

    providers = Providers(context={'_repolish_project': 'repolish'})

    preprocess_templates(setup_input, providers, config, base_dir)

    config.no_cookiecutter = True
    render_template(setup_input, providers, setup_output, config)

    out_logo = setup_output / 'repolish' / 'logo.png'
    assert out_logo.exists()
    assert out_logo.read_bytes().startswith(b'\x89PNG')


def test_render_with_jinja_raises_on_missing_variable(tmp_path: Path):
    """Missing variables should raise `UndefinedError` with StrictUndefined."""
    tpl = tmp_path / 'tpl-missing-var'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    (tpl / 'repolish' / 'README.md.jinja').write_text(
        '{{ cookiecutter.no_such_var }}\n',
        encoding='utf-8',
    )

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    create_cookiecutter_template(setup_input, [tpl])

    providers = Providers(context={'_repolish_project': 'repolish'})
    preprocess_templates(setup_input, providers, config, base_dir)

    config.no_cookiecutter = True
    with pytest.raises(UndefinedError):
        render_template(setup_input, providers, setup_output, config)


def test_render_with_jinja_raises_on_bad_path_syntax(tmp_path: Path):
    """Malformed Jinja in a path component should raise TemplateSyntaxError."""
    tpl = tmp_path / 'tpl-bad-path'
    bad_dir = tpl / 'repolish' / '{{cookiecutter.bad'
    bad_dir.mkdir(parents=True, exist_ok=True)
    (bad_dir / 'README.md.jinja').write_text('# ok\n', encoding='utf-8')

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    create_cookiecutter_template(setup_input, [tpl])

    providers = Providers(context={'_repolish_project': 'repolish', 'bad': 'x'})
    preprocess_templates(setup_input, providers, config, base_dir)

    config.no_cookiecutter = True
    with pytest.raises(TemplateSyntaxError):
        render_template(setup_input, providers, setup_output, config)


def test_render_with_jinja_raises_on_bad_template_content(tmp_path: Path):
    """Malformed Jinja in file *content* should raise TemplateSyntaxError and hit logger."""
    tpl = tmp_path / 'tpl-bad-content'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)

    # malformed Jinja (unclosed variable) in file content
    (tpl / 'repolish' / 'README.md.jinja').write_text(
        '{{ cookiecutter.broken ',
        encoding='utf-8',
    )

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    create_cookiecutter_template(setup_input, [tpl])

    providers = Providers(context={'_repolish_project': 'repolish'})
    preprocess_templates(setup_input, providers, config, base_dir)

    config.no_cookiecutter = True
    with pytest.raises(TemplateSyntaxError):
        render_template(setup_input, providers, setup_output, config)
