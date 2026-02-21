from pathlib import Path
from textwrap import dedent

import pytest
from jinja2 import TemplateSyntaxError, UndefinedError
from pydantic import BaseModel
from pytest_mock import MockerFixture

from repolish.builder import create_cookiecutter_template
from repolish.config.models import RepolishConfig
from repolish.hydration.rendering import render_template
from repolish.hydration.staging import prepare_staging, preprocess_templates
from repolish.loader import create_providers
from repolish.loader.types import FileMode, Providers, TemplateMapping


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


def test_render_with_file_mappings_generates_multiple_files(
    tmp_path: Path,
):
    """`TemplateMapping` entries should render a template multiple times with extra context."""
    tpl = tmp_path / 'tpl-multi'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)

    # Template named `item` (builder strips .jinja at copy time) containing a
    # placeholder that will be provided via extra_context in the mapping tuple.
    (tpl / 'repolish' / 'item.jinja').write_text(
        'FILE #{{ file_number }}\n',
        encoding='utf-8',
    )

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)

    create_cookiecutter_template(setup_input, [tpl])

    class ItemCtx(BaseModel):
        file_number: int

    providers = Providers(
        context={'_repolish_project': 'repolish'},
        file_mappings={
            'file-1.txt': TemplateMapping('item', ItemCtx(file_number=1)),
            'file-2.txt': TemplateMapping('item', ItemCtx(file_number=2)),
            'file-3.txt': TemplateMapping('item', ItemCtx(file_number=3)),
        },
    )

    preprocess_templates(setup_input, providers, config, base_dir)

    config.no_cookiecutter = True
    render_template(setup_input, providers, setup_output, config)

    for i in (1, 2, 3):
        out = setup_output / 'repolish' / f'file-{i}.txt'
        assert out.exists()
        assert out.read_text(encoding='utf-8').strip() == f'FILE #{i}'

    # Providers.file_mappings should be normalized to string source paths so
    # downstream code can continue to treat values as strings.
    assert providers.file_mappings['file-1.txt'] == 'file-1.txt'
    assert providers.file_mappings['file-2.txt'] == 'file-2.txt'
    assert providers.file_mappings['file-3.txt'] == 'file-3.txt'


def test_render_with_typed_extra_context_models(tmp_path: Path):
    """`TemplateMapping` entries may supply Pydantic model instances as extra context."""

    class ItemCtx(BaseModel):
        file_number: int

    tpl = tmp_path / 'tpl-multi-typed'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)

    (tpl / 'repolish' / 'item.jinja').write_text(
        'FILE #{{ file_number }}\n',
        encoding='utf-8',
    )

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)

    create_cookiecutter_template(setup_input, [tpl])

    providers = Providers(
        context={'_repolish_project': 'repolish'},
        file_mappings={
            'file-typed-1.txt': TemplateMapping(
                'item',
                ItemCtx(file_number=10),
            ),
            'file-typed-2.txt': TemplateMapping(
                'item',
                ItemCtx(file_number=20),
            ),
        },
    )

    preprocess_templates(setup_input, providers, config, base_dir)

    config.no_cookiecutter = True
    render_template(setup_input, providers, setup_output, config)

    assert (setup_output / 'repolish' / 'file-typed-1.txt').read_text(
        encoding='utf-8',
    ).strip() == 'FILE #10'
    assert (setup_output / 'repolish' / 'file-typed-2.txt').read_text(
        encoding='utf-8',
    ).strip() == 'FILE #20'

    # After rendering the mapping entries are normalized to destination paths
    assert providers.file_mappings['file-typed-1.txt'] == 'file-typed-1.txt'
    assert providers.file_mappings['file-typed-2.txt'] == 'file-typed-2.txt'


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


def test_provider_scoped_template_context_blocks_cross_provider_keys(
    tmp_path: Path,
    mocker: MockerFixture,
):
    """When provider-scoped context is enabled, migrated providers are.

    Rendered with their own context while unmigrated providers continue to
    receive merged context (compatibility fallback).
    """
    tpl = tmp_path / 'tpl-providers'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)

    # Two templates: one that expects only a_key, another that expects both
    (tpl / 'repolish' / 'item_a.jinja').write_text(
        'A={{ a_key }}\n',
        encoding='utf-8',
    )
    (tpl / 'repolish' / 'item_b.jinja').write_text(
        'A={{ a_key }} B={{ b_key }}\n',
        encoding='utf-8',
    )

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    create_cookiecutter_template(setup_input, [tpl])

    # Provider A (migrated): provides a_key and mapping that only needs its own context
    prov_a = tmp_path / 'prov-a'
    prov_a.mkdir()
    (prov_a / 'repolish.py').write_text(
        dedent(
            """
            from repolish.loader.types import TemplateMapping
            provider_migrated = True

            def create_context():
                return {'a_key': 'A'}

            def create_file_mappings():
                return {'a.txt': TemplateMapping('item_a', None)}
            """,
        ),
    )

    # Provider B (unmigrated): provides b_key and mapping that expects merged context
    prov_b = tmp_path / 'prov-b'
    prov_b.mkdir()
    (prov_b / 'repolish.py').write_text(
        dedent(
            """
            from repolish.loader.types import TemplateMapping

            def create_context():
                return {'b_key': 'B'}

            def create_file_mappings():
                return {'b.txt': TemplateMapping('item_b', None)}
            """,
        ),
    )

    providers = create_providers([str(prov_a), str(prov_b)])

    # Enable provider-scoped mapping rendering globally
    config.no_cookiecutter = True
    config.provider_scoped_template_context = True

    # Render: migrated provider's mapping sees only its context; unmigrated
    # provider's mapping sees merged context (compatibility)
    preprocess_templates(setup_input, providers, config, base_dir)

    # When provider-scoped rendering is enabled globally but not all
    # providers have opted into the new model, the renderer must raise.
    migrated_map = providers.provider_migrated
    assert any(migrated_map.values())
    assert any(not v for v in migrated_map.values())

    with pytest.raises(RuntimeError) as exc:
        render_template(setup_input, providers, setup_output, config)
    assert 'unmigrated providers' in str(exc.value)


def test_provider_scoped_template_context_allows_own_keys(tmp_path: Path):
    """Per-mapping rendering using only the declaring provider's context must.

    still allow templates that reference keys provided by the same provider.
    """
    tpl = tmp_path / 'tpl-owned'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    (tpl / 'repolish' / 'item.jinja').write_text(
        'X={{ my_key }}\n',
        encoding='utf-8',
    )

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    create_cookiecutter_template(setup_input, [tpl])

    # Provider supplies `my_key` and a mapping for `m.txt`; mark it migrated
    prov = tmp_path / 'prov'
    prov.mkdir()
    (prov / 'repolish.py').write_text(
        dedent(
            """
            from repolish.loader.types import TemplateMapping
            provider_migrated = True

            def create_context():
                return {'my_key': 'VAL'}

            def create_file_mappings():
                return {'m.txt': TemplateMapping('item', None)}
            """,
        ),
    )

    providers = create_providers([str(prov)])
    preprocess_templates(setup_input, providers, config, base_dir)

    # Enable provider-scoped mappings — should render fine because template only
    # references keys provided by the same provider.
    config.no_cookiecutter = True
    config.provider_scoped_template_context = True
    render_template(setup_input, providers, setup_output, config)
    assert (setup_output / 'repolish' / 'm.txt').read_text(
        encoding='utf-8',
    ).strip() == 'X=VAL'


def test_render_with_jinja_raises_on_missing_variable(tmp_path: Path):
    """Missing variables should raise `UndefinedError` with StrictUndefined.

    The raised exception message is enhanced with the path of the template so
    users know exactly which file failed to render.
    """
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
    with pytest.raises(UndefinedError) as exc:
        render_template(setup_input, providers, setup_output, config)
    # message should include the original Jinja error and note which file was
    # being rendered.
    msg = str(exc.value)
    assert 'while rendering' in msg
    assert 'no_such_var' in msg


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


# verify that errors raised while rendering individual TemplateMapping entries
# are collected and presented together to the caller. this guards against a
# single bad mapping hiding other failures.


def test_template_mapping_undefined_errors_are_collected(tmp_path: Path):
    tpl = tmp_path / 'tpl-maps'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    # template refers to a variable that will never be provided
    (tpl / 'repolish' / 'a.jinja').write_text(
        '{{ cookiecutter.a }}\n',
        encoding='utf-8',
    )

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    create_cookiecutter_template(setup_input, [tpl])

    providers = Providers(
        context={'_repolish_project': 'repolish'},
        file_mappings={
            'a.txt': TemplateMapping('a', None),
            'b.txt': TemplateMapping('a', None),
        },
    )

    preprocess_templates(setup_input, providers, config, base_dir)
    config.no_cookiecutter = True

    with pytest.raises(RuntimeError) as exc:
        render_template(setup_input, providers, setup_output, config)
    msg = str(exc.value)
    assert 'a.txt' in msg
    assert 'b.txt' in msg


# --- New unit tests to cover additional branches in rendering.py ---


def test_render_template_prunes_missing_and_unreadable_mapping(tmp_path: Path):
    """Public API: missing or unreadable TemplateMapping sources are pruned during render_template."""
    tpl = tmp_path / 'tpl'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    # create one real template so staging has content
    (tpl / 'repolish' / 'real.jinja').write_text('OK', encoding='utf-8')

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    create_cookiecutter_template(setup_input, [tpl])

    # mapping points to a missing template -> should be removed after render
    providers = Providers(
        context={'_repolish_project': 'repolish'},
        file_mappings={'cfg.yml': TemplateMapping('missing.tpl', None)},
    )

    preprocess_templates(setup_input, providers, config, base_dir)
    config.no_cookiecutter = True

    render_template(setup_input, providers, setup_output, config)

    assert 'cfg.yml' not in providers.file_mappings
    assert not (setup_output / 'repolish' / 'cfg.yml').exists()


def test_render_template_removes_delete_and_none_mappings(tmp_path: Path):
    """Public API: TemplateMapping entries with DELETE or None source are pruned and do not produce files."""
    tpl = tmp_path / 'tpl'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    (tpl / 'repolish' / 'item.jinja').write_text('X', encoding='utf-8')

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    create_cookiecutter_template(setup_input, [tpl])

    providers = Providers(
        context={'_repolish_project': 'repolish'},
        file_mappings={
            'will_delete.txt': TemplateMapping(
                None,
                None,
                file_mode=FileMode.DELETE,
            ),
            'none_src.txt': TemplateMapping(None, None),
            # valid one to ensure processing still occurs
            'good.txt': TemplateMapping('item', None),
        },
    )

    preprocess_templates(setup_input, providers, config, base_dir)
    config.no_cookiecutter = True

    render_template(setup_input, providers, setup_output, config)

    assert 'will_delete.txt' not in providers.file_mappings
    assert 'none_src.txt' not in providers.file_mappings
    # good mapping should be rendered and normalized
    assert (setup_output / 'repolish' / 'good.txt').exists()
    assert providers.file_mappings['good.txt'] == 'good.txt'


def test_render_template_raises_when_templatemappings_and_cookiecutter_enabled(
    tmp_path: Path,
):
    """Public API: TemplateMapping entries are incompatible with cookiecutter rendering."""
    tpl = tmp_path / 'tpl'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    (tpl / 'repolish' / 'item.jinja').write_text('X', encoding='utf-8')

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    create_cookiecutter_template(setup_input, [tpl])

    providers = Providers(
        context={},
        file_mappings={'x.txt': TemplateMapping('item', None)},
    )

    preprocess_templates(setup_input, providers, config, base_dir)

    # default config.no_cookiecutter is False -> render_template must raise
    with pytest.raises(
        RuntimeError,
        match=r'TemplateMapping entries require config\.no_cookiecutter=True',
    ):
        render_template(setup_input, providers, setup_output, config)
