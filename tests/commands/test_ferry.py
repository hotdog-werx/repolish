"""The ferry edge end to end: a real apply run delivers ferried data to the bundle.

No mocks — the session stages, preprocesses, renders, and applies a real
provider tree with the shared ``ferrying_family`` registered. The assertion
reads the mailbox every consumer will read: ``providers.ferry``.
"""

from pathlib import Path

from repolish.commands.apply.options import ResolvedSession
from repolish.commands.apply.session import (
    _relativize_ferry_dests,
    apply_session,
)
from repolish.config.models import RepolishConfig, ResolvedProviderInfo
from repolish.directives import FerriedItem
from repolish.providers import SessionBundle
from repolish.providers.models import GlobalContext
from repolish.providers.models.workspace import WorkspaceContext

_BADGES_BLOCK = '## repolish-keep-block[badges]: start="<!-- badges -->" end="<!-- /badges -->"\n'
_FOOTER_BLOCK = '## repolish-keep-block[footer|after-render]: start="<!-- footer -->" end="<!-- /footer -->"\n'


def test_apply_session_delivers_ferried_declarations_to_the_bundle(
    tmp_path: Path,
    ferrying_family: None,
) -> None:
    """One real run ferries both phases' declarations with project-relative dests.

    The plain keep block ferries in the pre-render phase (from the staged
    template); the ``|after-render`` block survives rendering and ferries in
    the after-render phase (from the rendered file). The session merges both
    in phase order and relativizes dests against the project root.
    """
    provider_dir = tmp_path / 'prov'
    templates = provider_dir / 'repolish'
    templates.mkdir(parents=True)
    (templates / 'README.md').write_text(
        '# Readme\n'
        + _BADGES_BLOCK
        + '<!-- badges -->\ntemplate default\n<!-- /badges -->\n'
        + _FOOTER_BLOCK
        + '<!-- footer -->\ntemplate default\n<!-- /footer -->\n',
        encoding='utf-8',
    )

    pid = provider_dir.as_posix()
    config = RepolishConfig(
        config_dir=tmp_path,
        providers_order=['prov'],
        providers={
            'prov': ResolvedProviderInfo(
                alias='prov',
                provider_root=provider_dir,
                resources_dir=provider_dir,
            ),
        },
        paused_files=[],
    )
    providers = SessionBundle()
    session = ResolvedSession(
        config_path=tmp_path / 'repolish.yaml',
        config=config,
        global_context=GlobalContext(
            workspace=WorkspaceContext(mode='standalone'),
        ),
        providers=providers,
        aliases=['prov'],
        alias_to_pid={'prov': pid},
        pid_to_alias={pid: 'prov'},
        resolved_symlinks={},
    )

    rc = apply_session(session, skip_post_process=True)

    assert rc == 0
    assert providers.ferry == {
        'ferry-family': (
            FerriedItem(dest='README.md', payload='badges'),
            FerriedItem(dest='README.md', payload='footer'),
        ),
    }


def test_relativize_ferry_dests_keeps_dests_outside_base_dir() -> None:
    """Dests outside the project root survive as-is; consumers decide what they mean.

    Session pairs always live under the project root, so this fallback is
    only reachable through :func:`run_phase`'s public pair API — pinned
    directly against the helper.
    """
    ferry: dict[str, tuple[FerriedItem, ...]] = {
        'ferry-family': (FerriedItem(dest='/elsewhere/staged.md', payload='badges'),),
    }

    result = _relativize_ferry_dests(ferry, Path('/proj'))

    assert result == ferry
