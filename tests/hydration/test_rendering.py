import sys
from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import BaseModel

from repolish.builder import stage_templates
from repolish.config import RepolishConfig
from repolish.hydration.rendering import (
    render_template,
)
from repolish.hydration.staging import prepare_staging, preprocess_templates
from repolish.providers import (
    BaseContext,
    FileMode,
    SessionBundle,
    TemplateMapping,
)
from repolish.providers.models import ProviderInfo, RepolishContext


def _make_template_dir(tmp_path: Path, name: str = 'example') -> Path:
    tpl = tmp_path / name
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    # Create a templated directory name + templated file content
    templated_dir = tpl / 'repolish' / '{{package_name}}'
    templated_dir.mkdir(parents=True, exist_ok=True)
    (templated_dir / 'README.md.jinja').write_text(
        dedent("""
        # {{ package_name }}

        Description: {{ description }}
        """),
        encoding='utf-8',
    )
    return tpl


def test_render_template_renders_with_jinja(tmp_path: Path):
    """Templates are rendered using Jinja2 with top-level context variables."""
    tpl = tmp_path / 'tpl'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    (tpl / 'repolish' / 'foo.jinja').write_text(
        'value={{ value }}',
        encoding='utf-8',
    )

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    stage_templates(setup_input, [tpl])

    class ValueCtx(BaseContext):
        value: str = 'hello'

    providers = SessionBundle(
        provider_contexts={'p': ValueCtx()},
        template_sources={'foo': 'p'},
    )
    preprocess_templates(setup_input, providers, base_dir)

    render_template(setup_input, providers, setup_output)
    assert (setup_output / 'repolish' / 'foo').read_text() == 'value=hello'


def test_render_resolves_context_with_windows_style_pid(
    tmp_path: Path,
):
    """A backslash-style provider id in template_sources still resolves to the correct context."""
    tpl = tmp_path / 'tpl'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    (tpl / 'repolish' / 'greet.txt.jinja').write_text(
        'hello={{ x }}',
        encoding='utf-8',
    )

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    stage_templates(setup_input, [tpl])

    class CtxX(BaseContext):
        x: int = 9

    providers = SessionBundle(
        provider_contexts={'P/subdir': CtxX()},
        # Simulate the backslash pid that Windows staging produces
        template_sources={'greet.txt': 'P\\subdir'},
    )
    preprocess_templates(setup_input, providers, base_dir)

    render_template(setup_input, providers, setup_output)

    out = setup_output / 'repolish' / 'greet.txt'
    assert out.read_text() == 'hello=9'


def test_render_with_jinja_exposes_context_as_top_level_variables(
    tmp_path: Path,
):
    """Provider context fields are available directly as top-level Jinja variables."""
    tpl = tmp_path / 'tpl-top-level'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)

    (tpl / 'repolish' / '{{package_name}}').mkdir(parents=True, exist_ok=True)
    (tpl / 'repolish' / '{{package_name}}' / 'README.md.jinja').write_text(
        'name: {{ package_name }}\n',
        encoding='utf-8',
    )

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    _, _ = stage_templates(setup_input, [tpl])

    class PackageCtx(BaseContext):
        package_name: str = 'acme'

    providers = SessionBundle(
        provider_contexts={'p': PackageCtx()},
        template_sources={'{{package_name}}/README.md': 'p'},
    )
    preprocess_templates(setup_input, providers, base_dir)

    render_template(setup_input, providers, setup_output)

    out_file = setup_output / 'repolish' / 'acme' / 'README.md'
    assert out_file.exists()
    text = out_file.read_text(encoding='utf-8')
    assert 'name: acme' in text


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

    _, _ = stage_templates(setup_input, [tpl])

    class ItemCtx(BaseModel):
        file_number: int

    providers = SessionBundle(
        file_mappings={
            'file-1.txt': TemplateMapping('item', ItemCtx(file_number=1)),
            'file-2.txt': TemplateMapping('item', ItemCtx(file_number=2)),
            'file-3.txt': TemplateMapping('item', ItemCtx(file_number=3)),
        },
    )

    preprocess_templates(setup_input, providers, base_dir)

    render_template(setup_input, providers, setup_output)

    prefix = '_repolish.'
    for i in (1, 2, 3):
        # output files are written with a prefix so skip the prefix when
        # checking existence/content.
        out = setup_output / 'repolish' / f'{prefix}file-{i}.txt'
        assert out.exists()
        assert out.read_text(encoding='utf-8').strip() == f'FILE #{i}'

    # After rendering, each entry is normalized to a TemplateMapping whose
    # source_template is the destination path.  source_provider and file_mode
    # are preserved so build_file_records can attribute files correctly.
    for key in ('file-1.txt', 'file-2.txt', 'file-3.txt'):
        tm = providers.file_mappings[key]
        assert isinstance(tm, TemplateMapping)
        assert tm.source_template == key


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

    _, _ = stage_templates(setup_input, [tpl])

    providers = SessionBundle(
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

    preprocess_templates(setup_input, providers, base_dir)

    render_template(setup_input, providers, setup_output)

    prefix = '_repolish.'
    assert (setup_output / 'repolish' / f'{prefix}file-typed-1.txt').read_text(
        encoding='utf-8',
    ).strip() == 'FILE #10'
    assert (setup_output / 'repolish' / f'{prefix}file-typed-2.txt').read_text(
        encoding='utf-8',
    ).strip() == 'FILE #20'

    # After rendering, each entry is normalized to a TemplateMapping whose
    # source_template is the destination path.
    for key in ('file-typed-1.txt', 'file-typed-2.txt'):
        tm = providers.file_mappings[key]
        assert isinstance(tm, TemplateMapping)
        assert tm.source_template == key


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

    stage_templates(setup_input, [tpl])

    providers = SessionBundle()

    preprocess_templates(setup_input, providers, base_dir)

    render_template(setup_input, providers, setup_output)

    out_logo = setup_output / 'repolish' / 'logo.png'
    assert out_logo.exists()
    assert out_logo.read_bytes().startswith(b'\x89PNG')


def test_render_with_jinja_raises_on_missing_variable(tmp_path: Path):
    """Missing variables are collected and raised together as a RuntimeError.

    All failing templates are reported at once so the user sees every problem
    in a single pass rather than getting stopped on the first bad file.
    """
    tpl = tmp_path / 'tpl-missing-var'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    (tpl / 'repolish' / 'README.md.jinja').write_text(
        '{{ no_such_var }}\n',
        encoding='utf-8',
    )

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    stage_templates(setup_input, [tpl])

    providers = SessionBundle()
    preprocess_templates(setup_input, providers, base_dir)

    with pytest.raises(RuntimeError) as exc:
        render_template(setup_input, providers, setup_output)
    msg = str(exc.value)
    assert 'no_such_var' in msg
    assert 'README.md' in msg


def test_render_with_jinja_raises_on_bad_path_syntax(tmp_path: Path):
    """Malformed Jinja in a path component is collected and raised as a RuntimeError."""
    tpl = tmp_path / 'tpl-bad-path'
    bad_dir = tpl / 'repolish' / '{{bad'
    bad_dir.mkdir(parents=True, exist_ok=True)
    (bad_dir / 'README.md.jinja').write_text('# ok\n', encoding='utf-8')

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    stage_templates(setup_input, [tpl])

    providers = SessionBundle()
    preprocess_templates(setup_input, providers, base_dir)

    with pytest.raises(RuntimeError) as exc:
        render_template(setup_input, providers, setup_output)
    assert 'path syntax error' in str(exc.value)


def test_render_with_jinja_raises_on_bad_template_content(tmp_path: Path):
    """Malformed Jinja in file *content* is collected and raised as a RuntimeError."""
    tpl = tmp_path / 'tpl-bad-content'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)

    # malformed Jinja (unclosed variable) in file content
    (tpl / 'repolish' / 'README.md.jinja').write_text(
        '{{ broken ',
        encoding='utf-8',
    )

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    stage_templates(setup_input, [tpl])

    providers = SessionBundle()
    preprocess_templates(setup_input, providers, base_dir)

    with pytest.raises(RuntimeError):
        render_template(setup_input, providers, setup_output)


# verify that errors raised while rendering individual TemplateMapping entries
# are collected and presented together to the caller. this guards against a
# single bad mapping hiding other failures.


def test_template_mapping_undefined_errors_are_collected(tmp_path: Path):
    tpl = tmp_path / 'tpl-maps'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    # template refers to a variable that will never be provided
    (tpl / 'repolish' / 'a.jinja').write_text(
        '{{ a }}\n',
        encoding='utf-8',
    )

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    stage_templates(setup_input, [tpl])

    providers = SessionBundle(
        file_mappings={
            'a.txt': TemplateMapping('a', None),
            'b.txt': TemplateMapping('a', None),
        },
    )

    preprocess_templates(setup_input, providers, base_dir)

    with pytest.raises(RuntimeError) as exc:
        render_template(setup_input, providers, setup_output)
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
    stage_templates(setup_input, [tpl])

    # mapping points to a missing template -> should be removed after render
    providers = SessionBundle(
        file_mappings={'cfg.yml': TemplateMapping('missing.tpl', None)},
    )

    preprocess_templates(setup_input, providers, base_dir)

    render_template(setup_input, providers, setup_output)

    assert 'cfg.yml' not in providers.file_mappings
    assert not (setup_output / 'repolish' / 'cfg.yml').exists()


def test_render_template_removes_delete_and_none_mappings(tmp_path: Path):
    """Public API: TemplateMapping entries with DELETE or None source are pruned and do not produce files."""
    tpl = tmp_path / 'tpl'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    (tpl / 'repolish' / 'item.jinja').write_text('X', encoding='utf-8')

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    stage_templates(setup_input, [tpl])

    providers = SessionBundle(
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

    preprocess_templates(setup_input, providers, base_dir)

    render_template(setup_input, providers, setup_output)

    assert 'will_delete.txt' not in providers.file_mappings
    assert 'none_src.txt' not in providers.file_mappings
    # good mapping should be rendered with the prefix but normalization
    # still reports the unprefixed destination path via TemplateMapping.
    assert (setup_output / 'repolish' / '_repolish.good.txt').exists()
    tm = providers.file_mappings['good.txt']
    assert isinstance(tm, TemplateMapping)
    assert tm.source_template == 'good.txt'


def test_render_template_mappings_work_with_jinja(
    tmp_path: Path,
):
    """Public API: TemplateMapping entries are rendered via Jinja."""
    tpl = tmp_path / 'tpl'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    (tpl / 'repolish' / 'item.jinja').write_text('X', encoding='utf-8')

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    stage_templates(setup_input, [tpl])

    providers = SessionBundle(
        file_mappings={'x.txt': TemplateMapping('item', None)},
    )

    preprocess_templates(setup_input, providers, base_dir)

    # template mappings are always supported; jinja handles them directly
    render_template(setup_input, providers, setup_output)


def test_process_template_mappings_skips_string_entries(tmp_path: Path):
    """String-valued file_mappings entries are ignored by the mapping render phase."""
    tpl = tmp_path / 'tpl'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    (tpl / 'repolish' / 'item.jinja').write_text('rendered', encoding='utf-8')

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    stage_templates(setup_input, [tpl])

    providers = SessionBundle(
        file_mappings={
            # plain string entry — must be skipped by _process_template_mappings
            'plain.txt': 'item',
            # TemplateMapping entry — must still be rendered
            'mapped.txt': TemplateMapping('item', None),
        },
    )

    preprocess_templates(setup_input, providers, base_dir)
    render_template(setup_input, providers, setup_output)

    # the TemplateMapping entry is materialized with the prefixed name
    assert (setup_output / 'repolish' / '_repolish.mapped.txt').exists()
    # the string entry is untouched in file_mappings (not normalized to dest path)
    assert providers.file_mappings['plain.txt'] == 'item'


def test_provider_info_bad_version_renders_none_not_crash(
    tmp_path: Path,
) -> None:
    """A non-parseable version string makes major_version None in templates.

    Jinja2 renders None as the literal string "None" rather than raising;
    this test pins that behaviour so we know bad version strings are silent
    rather than breaking the rendering pipeline.
    """
    tpl = tmp_path / 'tpl'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    (tpl / 'repolish' / 'info.txt.jinja').write_text(
        'major={{ repolish.provider.major_version }}\n',
        encoding='utf-8',
    )

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    stage_templates(setup_input, [tpl])

    ctx = BaseContext(
        repolish=RepolishContext(
            provider=ProviderInfo(alias='mypkg', version='not-a-version'),
        ),
    )

    providers = SessionBundle(
        provider_contexts={'p': ctx},
        template_sources={'info.txt': 'p'},
    )

    preprocess_templates(setup_input, providers, base_dir)
    render_template(setup_input, providers, setup_output)

    out = setup_output / 'repolish' / 'info.txt'
    assert out.exists()
    # None serialises to the string "None" in Jinja2 — no crash, no empty string
    assert out.read_text(encoding='utf-8').strip() == 'major=None'


def test_render_template_skips_suppressed_sources(tmp_path: Path) -> None:
    """A broken template listed in suppressed_sources is not rendered and causes no error."""
    tpl = tmp_path / 'tpl'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    # This template references an undefined variable — it would fail if rendered.
    (tpl / 'repolish' / 'broken.txt').write_text(
        '{{ undefined_variable }}',
        encoding='utf-8',
    )
    # A normal template that should still be rendered.
    (tpl / 'repolish' / 'good.txt').write_text('ok', encoding='utf-8')

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    stage_templates(setup_input, [tpl])

    providers = SessionBundle(suppressed_sources={'broken.txt'})
    preprocess_templates(setup_input, providers, base_dir)

    # Must not raise even though broken.txt has an undefined variable.
    render_template(setup_input, providers, setup_output)

    assert not (setup_output / 'repolish' / 'broken.txt').exists()
    assert (setup_output / 'repolish' / 'good.txt').read_text() == 'ok'


@pytest.mark.skipif(
    sys.platform == 'win32',
    reason='Windows does not support Unix executable bits',
)
def test_render_template_preserves_executable_bit(tmp_path: Path) -> None:
    """The executable bit on a template file is preserved in the rendered output."""
    tpl = tmp_path / 'tpl'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    script = tpl / 'repolish' / 'setup.sh'
    script.write_text('#!/bin/bash\necho hello\n', encoding='utf-8')
    script.chmod(0o755)

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    stage_templates(setup_input, [tpl])

    providers = SessionBundle()
    preprocess_templates(setup_input, providers, base_dir)
    render_template(setup_input, providers, setup_output)

    out = setup_output / 'repolish' / 'setup.sh'
    assert out.exists()
    assert out.stat().st_mode & 0o111, 'executable bit must be preserved after rendering'


def test_render_template_skips_filemode_suppress(tmp_path: Path) -> None:
    """FileMode.SUPPRESS on a TemplateMapping prevents the source template from rendering."""
    tpl = tmp_path / 'tpl'
    (tpl / 'repolish').mkdir(parents=True, exist_ok=True)
    (tpl / 'repolish' / 'wip.txt').write_text('{{ boom }}', encoding='utf-8')
    (tpl / 'repolish' / 'stable.txt').write_text('fine', encoding='utf-8')

    config = RepolishConfig(config_dir=tmp_path)
    base_dir, setup_input, setup_output = prepare_staging(config)
    stage_templates(setup_input, [tpl])

    # Simulate what exchange._apply_annotated_tm does for SUPPRESS:
    # source_template path ends up in suppressed_sources, nothing in file_mappings.
    providers = SessionBundle(suppressed_sources={'wip.txt'})
    preprocess_templates(setup_input, providers, base_dir)

    render_template(setup_input, providers, setup_output)

    assert not (setup_output / 'repolish' / 'wip.txt').exists()
    assert (setup_output / 'repolish' / 'stable.txt').read_text() == 'fine'
