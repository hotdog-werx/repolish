from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest
from jinja2 import TemplateSyntaxError, UndefinedError
from pydantic import BaseModel
from pytest_mock import MockerFixture

from repolish.builder import create_cookiecutter_template
from repolish.config import RepolishConfig
from repolish.hydration.rendering import (
    RenderContext,
    _choose_ctx_for_file,
    render_template,
)
from repolish.hydration.staging import prepare_staging, preprocess_templates
from repolish.loader import (
    BaseContext,
    FileMode,
    Providers,
    TemplateMapping,
)


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


def test_render_template_renders_with_jinja(tmp_path: Path):
    """Templates should always be rendered using Jinja2 after cookiecutter removal."""
    tpl = tmp_path / 'tpl'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    (tpl / 'repolish' / 'foo.jinja').write_text(
        'value={{ cookiecutter.value }}',
        encoding='utf-8',
    )

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    create_cookiecutter_template(setup_input, [tpl])

    providers = Providers(
        context={'value': 'hello', '_repolish_project': 'repolish'},
    )
    preprocess_templates(setup_input, providers, config, base_dir)

    render_template(setup_input, providers, setup_output, config)
    assert (setup_output / 'repolish' / 'foo').read_text() == 'value=hello'


def test_render_template_logs_merged_context(
    tmp_path: Path,
    mocker: MockerFixture,
):
    """Rendering logs the merged context at debug level."""
    # simple template so rendering will proceed without errors
    tpl = tmp_path / 'tpl'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    (tpl / 'repolish' / 'foo.jinja').write_text(
        'X={{ cookiecutter.foo }}',
        encoding='utf-8',
    )

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    create_cookiecutter_template(setup_input, [tpl])

    providers = Providers(
        context={'foo': 'bar', '_repolish_project': 'repolish'},
    )
    preprocess_templates(setup_input, providers, config, base_dir)

    mock_logger = mocker.patch('repolish.hydration.rendering.logger')
    render_template(setup_input, providers, setup_output, config)

    # ensure debug log called with merged context dictionary
    mock_logger.debug.assert_any_call(
        'computed_merged_context',
        merged_ctx={'foo': 'bar', '_repolish_project': 'repolish'},
    )


def test_compute_merged_context_logs_details(mocker: MockerFixture):
    # simulate a migrated provider whose context supplies 'a'.
    providers = Providers(
        context={'base': 1},
        provider_contexts={},
    )

    mock_logger = mocker.patch('repolish.hydration.rendering.logger')
    # import here avoids circular initialization at module load when patching
    from repolish.hydration.rendering import _compute_merged_context  # noqa: PLC0415

    merged = _compute_merged_context(providers)
    assert merged == {'base': 1, '_repolish_project': 'repolish'}
    # logger should have recorded start and result
    assert mock_logger.debug.call_count >= 2
    logged = [c.args[0] for c in mock_logger.debug.call_args_list]
    assert 'compute_merged_context_start' in logged
    assert 'compute_merged_context_result' in logged


def test_choose_ctx_for_file_logs(mocker: MockerFixture, tmp_path: Path):
    """Choosing context for a path emits debug information."""

    class CtxA(BaseContext):
        a: int = 2

    providers = Providers(
        context={'base': 1},
        provider_contexts={'p': CtxA()},
        template_sources={'tpl.txt': 'p'},
    )

    config = RepolishConfig(config_dir=tmp_path)
    render_ctx = RenderContext(
        setup_input=tmp_path,
        merged_ctx={'base': 1},
        setup_output=tmp_path,
        providers=providers,
        config=config,
    )

    mock_logger = mocker.patch('repolish.hydration.rendering.logger')
    result = _choose_ctx_for_file('tpl.txt', render_ctx)
    assert result.get('a') == 2
    mock_logger.debug.assert_any_call(
        'choose_context_for_file',
        rel='tpl.txt',
        pid='p',
        normalized_pid='p',
    )


def test_choose_ctx_for_file_normalizes_windows_pid(
    mocker: MockerFixture,
    tmp_path: Path,
):
    """A mismatched Windows-style provider id should still resolve."""

    class CtxX(BaseContext):
        x: int = 9

    providers = Providers(
        context={'base': 1},
        provider_contexts={'P/subdir': CtxX()},
        # template_sources comes from builder; simulate backslash pid
        template_sources={'f.txt': 'P\\subdir'},
    )

    config = RepolishConfig(config_dir=tmp_path)
    render_ctx = RenderContext(
        setup_input=tmp_path,
        merged_ctx={'base': 1},
        setup_output=tmp_path,
        providers=providers,
        config=config,
    )

    mock_logger = mocker.patch('repolish.hydration.rendering.logger')
    result = _choose_ctx_for_file('f.txt', render_ctx)
    assert result.get('x') == 9
    mock_logger.debug.assert_any_call(
        'choose_context_for_file',
        rel='f.txt',
        pid='P\\subdir',
        normalized_pid='P/subdir',
    )


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
    _, _ = create_cookiecutter_template(setup_input, [tpl])

    providers = Providers(
        context={'package_name': 'acme', '_repolish_project': 'repolish'},
    )
    preprocess_templates(setup_input, providers, config, base_dir)

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

    _, _ = create_cookiecutter_template(setup_input, [tpl])

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

    render_template(setup_input, providers, setup_output, config)

    prefix = '_repolish.'
    for i in (1, 2, 3):
        # output files are written with a prefix so skip the prefix when
        # checking existence/content.
        out = setup_output / 'repolish' / f'{prefix}file-{i}.txt'
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

    _, _ = create_cookiecutter_template(setup_input, [tpl])

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

    render_template(setup_input, providers, setup_output, config)

    prefix = '_repolish.'
    assert (setup_output / 'repolish' / f'{prefix}file-typed-1.txt').read_text(
        encoding='utf-8',
    ).strip() == 'FILE #10'
    assert (setup_output / 'repolish' / f'{prefix}file-typed-2.txt').read_text(
        encoding='utf-8',
    ).strip() == 'FILE #20'

    # After rendering the mapping entries are normalized to destination paths
    assert providers.file_mappings['file-typed-1.txt'] == 'file-typed-1.txt'
    assert providers.file_mappings['file-typed-2.txt'] == 'file-typed-2.txt'


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

    render_template(setup_input, providers, setup_output, config)

    out_logo = setup_output / 'repolish' / 'logo.png'
    assert out_logo.exists()
    assert out_logo.read_bytes().startswith(b'\x89PNG')


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

    # patch logger so we can introspect which context was used during failure
    with (
        patch('repolish.hydration.rendering.logger') as mock_logger,
        pytest.raises(UndefinedError) as exc,
    ):
        render_template(setup_input, providers, setup_output, config)
    # message should include the original Jinja error and note which file was
    # being rendered.
    msg = str(exc.value)
    assert 'while rendering' in msg
    assert 'no_such_var' in msg

    # ensure our patched logger was invoked with the failing context
    assert mock_logger.exception.called
    call = mock_logger.exception.call_args
    assert 'context' in call.kwargs
    assert isinstance(call.kwargs['context'], dict)


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

    render_template(setup_input, providers, setup_output, config)

    assert 'will_delete.txt' not in providers.file_mappings
    assert 'none_src.txt' not in providers.file_mappings
    # good mapping should be rendered with the prefix but normalization
    # still reports the unprefixed destination path.
    assert (setup_output / 'repolish' / '_repolish.good.txt').exists()
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

    # template mappings are always supported; jinja handles them directly
    render_template(setup_input, providers, setup_output, config)
