"""The input contract witness: ResolvedSession satisfies SummarySession.

`SummarySession` is structural, so this is a static check only — ty fails
the build if the apply pipeline's `ResolvedSession` stops providing what
derivation reads. No runtime assertions needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from repolish.commands.apply.options import ResolvedSession
from repolish.config.models import RepolishConfig
from repolish.providers.models import (
    GlobalContext,
    SessionBundle,
    WorkspaceContext,
)

if TYPE_CHECKING:
    from pathlib import Path

    from repolish.summaries.contract import SummarySession


def test_resolved_session_satisfies_the_contract(tmp_path: Path) -> None:
    config = RepolishConfig(config_dir=tmp_path, providers={})
    session = ResolvedSession(
        config_path=tmp_path / 'repolish.yaml',
        config=config,
        global_context=GlobalContext(
            workspace=WorkspaceContext(mode='standalone'),
        ),
        providers=SessionBundle(),
        aliases=[],
        alias_to_pid={},
        pid_to_alias={},
        provider_filter=None,
    )
    # The assignment is the test: annotation-incompatible members fail ty.
    witness: SummarySession = session
    assert witness.config is config
