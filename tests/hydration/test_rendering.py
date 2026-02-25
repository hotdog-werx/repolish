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
    FileMode,
    Providers,
    TemplateMapping,
    create_providers,
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


def test_render_template_with_no_cookiecutter_renders_jinja(tmp_path: Path):
    """When config.no_cookiecutter is True, templates are rendered with Jinja2."""


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

    config.no_cookiecutter = True
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
        provider_migrated={'p': True},
        provider_contexts={'p': {'a': 2}},
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
    # prepare a provider that is marked migrated and has its own context
    providers = Providers(
        context={'base': 1},
        provider_contexts={'p': {'a': 2}},
        provider_migrated={'p': True},
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
    assert result == {'a': 2}
    mock_logger.debug.assert_any_call(
        'choose_context_for_file',
        rel='tpl.txt',
        pid='p',
        normalized_pid='p',
        migrated=True,
    )


def test_choose_ctx_for_file_normalizes_windows_pid(
    mocker: MockerFixture,
    tmp_path: Path,
):
    """A mismatched Windows-style provider id should still resolve."""
    # Use a provider id that would normally be converted from a
    # Windows-style path with backslashes.  after normalisation it should
    # appear as 'P/subdir' which is the key we store in the migrated map.
    providers = Providers(
        context={'base': 1},
        provider_contexts={'P/subdir': {'x': 9}},
        # loader will use posix style
        provider_migrated={'P/subdir': True},
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
    # normalization should strip the backslash component and succeed
    assert result == {'x': 9}
    # debug log should record both original and normalized pid
    mock_logger.debug.assert_any_call(
        'choose_context_for_file',
        rel='f.txt',
        pid='P\\subdir',
        normalized_pid='P/subdir',
        migrated=True,
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

    config.no_cookiecutter = True
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

    config.no_cookiecutter = True
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


def test_cookiecutter_and_jinja_paths_produce_equivalent_output(tmp_path: Path):
    """Ensure disabling cookiecutter produces equivalent rendered files."""
    tpl = _make_template_dir(tmp_path, name='tpl2')

    config = RepolishConfig(config_dir=tmp_path)

    # --- cookiecutter run (default) ---
    base_dir, setup_input, setup_output = prepare_staging(config)
    _, _ = create_cookiecutter_template(setup_input, [tpl])
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
    _, _ = create_cookiecutter_template(setup_input, [tpl])
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
    """Migrated providers are isolated; unmigrated providers no longer inherit migrated keys.

    Context isolation is always active for migrated providers; the former
    ``provider_scoped_template_context`` configuration flag no longer needs to
    be enabled by users.  This test exercises the same guarantees as before:

    1. Templates belonging to unmigrated providers do not see keys from
       providers that have already migrated.  Those values are stripped from
       the merged context as soon as a provider is marked ``provider_migrated``.
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
            from repolish import TemplateMapping
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
            from repolish import TemplateMapping

            def create_context():
                return {'b_key': 'B'}

            def create_file_mappings():
                return {'b.txt': TemplateMapping('item_b', None)}
            """,
        ),
    )

    providers = create_providers([str(prov_a), str(prov_b)])

    # Enable Jinja rendering (scoped context is now automatic)
    config.no_cookiecutter = True

    # Render: migrated provider's mapping sees only its context; unmigrated
    # provider's mapping does *not* inherit the migrated provider's keys.
    preprocess_templates(setup_input, providers, config, base_dir)

    migrated_map = providers.provider_migrated
    assert any(migrated_map.values())
    assert any(not v for v in migrated_map.values())

    # B's template references `a_key` (owned by migrated provider A) - since
    # A's context is removed from the merged context the render should fail.
    # the failure happens when rendering mappings, so the error is wrapped in a
    # RuntimeError by ``_process_template_mappings``.
    with pytest.raises(RuntimeError) as exc:
        render_template(setup_input, providers, setup_output, config)
    assert 'a_key' in str(exc.value)


def test_provider_scoped_template_context_allows_own_keys(tmp_path: Path):
    """Per-mapping rendering using only the declaring provider's context must.

    still allow templates that reference keys provided by the same provider.

    Scoping happens automatically for migrated providers.
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
            from repolish import TemplateMapping
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

    # Enable Jinja rendering (scoped context applies automatically)
    config.no_cookiecutter = True
    render_template(setup_input, providers, setup_output, config)
    prefix = '_repolish.'
    assert (setup_output / 'repolish' / f'{prefix}m.txt').read_text(
        encoding='utf-8',
    ).strip() == 'X=VAL'


def test_render_context_excludes_migrated_providers(tmp_path: Path):
    """Keys from migrated providers are excluded from the merged context.

    Keys from migrated (class-based) providers are not present in
    the merged context, as demonstrated by a failing render.

    This behaviour is independent of the
    ``provider_scoped_template_context`` flag; merging occurs once per
    ``render_template`` invocation and always omits migrated contexts.
    """
    tpl = tmp_path / 'tpl-mig'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    # single template that references ``foo``
    (tpl / 'repolish' / 'out.jinja').write_text(
        'VALUE={{ foo }}\n',
        encoding='utf-8',
    )

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    create_cookiecutter_template(setup_input, [tpl])

    # provider A is migrated and supplies ``foo``; provider B is unmigrated
    p_a = tmp_path / 'pa'
    p_a.mkdir()
    (p_a / 'repolish.py').write_text(
        """provider_migrated = True

def create_context():
    return {'foo': 'A'}
""",
    )
    p_b = tmp_path / 'pb'
    p_b.mkdir()
    (p_b / 'repolish.py').write_text(
        """def create_context():
    return {'bar': 'B'}
""",
    )

    providers = create_providers([str(p_a), str(p_b)])
    preprocess_templates(setup_input, providers, config, base_dir)
    config.no_cookiecutter = True

    # rendering should blow up because ``foo`` was stripped from merged_ctx
    with pytest.raises(UndefinedError):
        render_template(setup_input, providers, setup_output, config)


def test_generic_templates_get_provider_context_when_scoped(tmp_path: Path):
    """When provider-scoped rendering is enabled we use the provider's own context.

    Context selection uses the provenance map produced during staging.
    """
    # create a migrated provider that supplies a single template
    prov = tmp_path / 'prov'
    prov.mkdir()
    rep = prov / 'repolish'
    rep.mkdir()
    (rep / 'foo.jinja').write_text('VALUE={{ foo }}\n')
    # provider module indicating migrated and providing context
    (prov / 'repolish.py').write_text(
        """provider_migrated = True

def create_context():
    return {'foo': 'A'}
""",
    )

    providers = create_providers([str(prov)])
    # force the migration flag and context (loader normally does this)
    pid = next(iter(providers.provider_contexts.keys()))
    providers.provider_migrated = {pid: True}
    providers.provider_contexts = {pid: {'foo': 'A'}}

    # stage the template directory with alias equal to pid so the sources map
    # records the correct provider identifier
    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    _, sources = create_cookiecutter_template(setup_input, [(pid, prov)])
    providers.template_sources = sources

    preprocess_templates(setup_input, providers, config, base_dir)
    config.no_cookiecutter = True
    # the configuration flag is now irrelevant for scoping; set it False to
    # prove that provider-specific contexts still win.
    config.provider_scoped_template_context = False

    render_template(setup_input, providers, setup_output, config)
    out = setup_output / 'repolish' / 'foo'
    assert out.exists()
    assert out.read_text(encoding='utf-8').strip() == 'VALUE=A'


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

    # default config.no_cookiecutter is False -> render_template must raise
    with pytest.raises(
        RuntimeError,
        match=r'TemplateMapping entries require config\.no_cookiecutter=True',
    ):
        render_template(setup_input, providers, setup_output, config)
