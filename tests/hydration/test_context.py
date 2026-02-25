"""Tests for hydration context building functionality."""

from pathlib import Path
from textwrap import dedent
from typing import cast

from repolish.config import RepolishConfig, ResolvedProviderInfo
from repolish.hydration.context import build_final_providers


def test_config_level_provenance(tmp_path: Path):
    """Test that config-level delete file decisions override provider decisions with proper provenance."""
    # Create a provider that requests deletion of 'a.txt'
    d = tmp_path / 'prov0'
    d.mkdir()
    (d / 'repolish.py').write_text(
        dedent("""
        delete_files = ['a.txt']
    """),
    )

    cfg = RepolishConfig.model_validate(
        {
            'config_dir': tmp_path,
            'directories': [d],
            'context': {},
            'anchors': {},
            'post_process': [],
            # config negates a.txt and adds b.txt
            'delete_files': ['!a.txt', 'b.txt'],
        },
    )

    providers = build_final_providers(cfg)

    # Final delete_files should include b.txt but not a.txt
    got = {Path(p) for p in providers.delete_files}
    assert Path('b.txt') in got
    assert Path('a.txt') not in got

    # Provenance: last decision for a.txt must be from the config and be 'keep'
    a_hist = providers.delete_history.get('a.txt')
    assert a_hist
    assert len(a_hist) >= 1
    assert a_hist[-1].source == cfg.config_dir.as_posix()
    assert a_hist[-1].action.value == 'keep'

    # Provenance: last decision for b.txt must be from the config and be 'delete'
    b_hist = providers.delete_history.get('b.txt')
    assert b_hist
    assert len(b_hist) >= 1
    assert b_hist[-1].source == cfg.config_dir.as_posix()
    assert b_hist[-1].action.value == 'delete'

    # even when using the deprecated `directories` key the
    # Providers object still exposes the new metadata fields so client
    # code doesn't need special-case logic.  we don't care how many entries
    # are present (module-style loaders always add a key) but the attributes
    # themselves must exist and be the expected types.
    assert isinstance(providers.provider_contexts, dict)
    assert isinstance(providers.provider_migrated, dict)
    # there should be at most one provider in this simple scenario
    assert len(providers.provider_contexts) <= 1
    assert len(providers.provider_migrated) <= 1


def test_per_provider_context_override(tmp_path: Path):
    """A user config can override the context produced by a single provider.

    The override should affect both the per-provider context map and the
    flattened context that ends up in `Providers.context` so that other
    providers (and template rendering) see the updated value.
    """
    # create a simple provider that returns one key
    prov = tmp_path / 'prov'
    prov.mkdir()
    (prov / 'repolish.py').write_text(
        """def create_context():
    return {'foo': 'orig'}
""",
    )

    # we build a minimal ResolvedProviderInfo so that
    # `build_final_providers` can map the alias back to the provider path

    info = ResolvedProviderInfo(
        alias='p',
        target_dir=prov,
        templates_dir='',
        symlinks=[],
        context={'foo': 'override'},
    )
    cfg = RepolishConfig.model_validate(
        {
            'config_dir': tmp_path,
            'directories': [prov],
            'context': {},
            'context_overrides': {},
            'anchors': {},
            'post_process': [],
            'delete_files': [],
            'providers': {prov.as_posix(): info},
        },
    )

    providers = build_final_providers(cfg)
    pid = prov.as_posix()
    # the override should be written into providers.provider_contexts
    ctx = cast('dict', providers.provider_contexts.get(pid, {}))
    assert ctx.get('foo') == 'override'
    global_ctx = cast('dict', providers.context)
    assert global_ctx.get('foo') == 'override'


def test_per_provider_context_override_with_templates_dir(tmp_path: Path):
    """Overrides still work when the provider uses a non-empty templates_dir.

    Previously we constructed provider IDs from `target_dir` alone, which
    mismatched the directories passed to the loader when `templates_dir` was
    non-empty.  This regression meant real applications would never apply the
    override even though the unit tests (which used `templates_dir=''`) had
    passed.
    """
    prov = tmp_path / 'prov'
    prov.mkdir()
    sub = prov / 'templates'
    sub.mkdir()
    # when templates_dir is non-empty the provider module lives under the
    # templates directory just like the real linking code uses (see
    # tests/deprecated/conftest.py for reference)
    (sub / 'repolish.py').write_text(
        """def create_context():
    return {'foo': 'orig'}
""",
    )

    info = ResolvedProviderInfo(
        alias='p',
        target_dir=prov,
        templates_dir='templates',
        symlinks=[],
        context={'foo': 'override'},
    )
    # when resolving, directories list will contain prov/templates
    cfg = RepolishConfig.model_validate(
        {
            'config_dir': tmp_path,
            'directories': [sub],
            'context': {},
            'context_overrides': {},
            'anchors': {},
            'post_process': [],
            'delete_files': [],
            'providers': {prov.as_posix(): info},
        },
    )

    providers = build_final_providers(cfg)
    pid = sub.as_posix()
    ctx = cast('dict', providers.provider_contexts.get(pid, {}))
    assert ctx.get('foo') == 'override'
    global_ctx = cast('dict', providers.context)
    assert global_ctx.get('foo') == 'override'


def test_provider_context_overrides_dotted(tmp_path: Path):
    """Dotted-path overrides on a provider config should patch the captured context."""
    prov = tmp_path / 'prov'
    prov.mkdir()
    (prov / 'repolish.py').write_text(
        """def create_context():
    return {'nested': {'key': 'orig'}}
""",
    )

    info = ResolvedProviderInfo(
        alias='p',
        target_dir=prov,
        templates_dir='',
        symlinks=[],
        context=None,
        context_overrides={'nested.key': 'patched', 'new': 123},
    )
    cfg = RepolishConfig.model_validate(
        {
            'config_dir': tmp_path,
            'directories': [prov],
            'context': {},
            'context_overrides': {},
            'anchors': {},
            'post_process': [],
            'delete_files': [],
            'providers': {prov.as_posix(): info},
        },
    )

    providers = build_final_providers(cfg)
    pid = prov.as_posix()
    ctx = cast('dict', providers.provider_contexts.get(pid, {}))
    assert ctx['nested']['key'] == 'patched'
    assert ctx['new'] == 123
    global_ctx = cast('dict', providers.context)
    assert global_ctx['nested']['key'] == 'patched'
    assert global_ctx['new'] == 123
