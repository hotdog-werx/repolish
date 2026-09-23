"""The input contracts: what each finished surface hands to summaries.

Four surfaces, four contracts, one shape each:

- apply: `SummarySession`, everything the apply derivation reads.
- post-process: `PostProcessSession`, the narrow slice the post-process
  group derivation and the session labeler need.
- link: `LinkResult`, the collected declarations of one link pass.
- insertion catalog: `InsertionCatalogSession`, the registry slice the
  catalog derivation reads (`repolish list-insertions`).

The protocols are structural, so the apply pipeline's `ResolvedSession`
satisfies them without wrapping or conversion — but the dependency arrow
stays honest: the pipeline *delivers* something that matches what
summaries asks for; summaries never imports the pipeline at runtime. The
member lists are the complete set of fields derivation reads, annotated
verbatim to match the delivered model, so adding a field to a contract is
a deliberate act ty verifies at every call site.

Hold-back kinds derivation must keep distinct (never collapse them):
`config.paused_files` is the loud, temporary escape hatch (the run logs
`files_paused` every time), while provider `None` mappings (SUPPRESSED)
and `overrides.file_mappings: false` (DISABLED) are silent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path

    from repolish.commands.apply.options import InsertionFileResult
    from repolish.config.models import RepolishConfig
    from repolish.config.models.provider import ProviderCopy, ProviderSymlink
    from repolish.postprocess.models import PostProcessRun
    from repolish.providers.models import (
        GlobalContext,
        SessionBundle,
        ValidationResult,
    )


class SummarySession(Protocol):
    """What the apply derivation receives once a run has finished."""

    config: RepolishConfig
    global_context: GlobalContext
    providers: SessionBundle
    aliases: list[str]
    alias_to_pid: dict[str, str]
    pid_to_alias: dict[str, str]
    provider_filter: list[str] | None
    apply_result: dict[str, str]
    paused_copies: dict[str, list[str]]
    resolved_copies: dict[str, list[ProviderCopy]]
    resolved_symlinks: dict[str, list[ProviderSymlink]]
    promoted_records: list
    promoted_apply_result: dict[str, str]
    validation_results: dict[str, dict[str, ValidationResult]]
    validation_reports: dict[str, str]
    insertion_results: dict[str, InsertionFileResult]
    provider_insertion_results: dict[str, dict[str, InsertionFileResult]]
    post_process_runs: list[tuple[str, PostProcessRun]]
    post_process_reports: list[Path]


class PostProcessSession(Protocol):
    """What the post-process derivation receives once a run has finished.

    A deliberate slice of `SummarySession`: commands and their reports,
    plus the two fields the session labeler reads (workspace mode and the
    member-name provider contexts). A session that never ran
    post-process commands still satisfies this — it just yields no group.
    """

    config: RepolishConfig
    global_context: GlobalContext
    providers: SessionBundle
    post_process_runs: list[tuple[str, PostProcessRun]]
    post_process_reports: list[Path]


class InsertionCatalogSession(Protocol):
    """What the insertion catalog receives once a session resolves.

    `repolish list-insertions` reads the insertion registries
    (`providers.file_insertions` + `providers.insertion_sources`) and
    maps provider ids back to aliases through `pid_to_alias`.
    """

    providers: SessionBundle
    pid_to_alias: dict[str, str]


@dataclass(frozen=True)
class LinkResult:
    """What one link pass hands over: the declarations it resolved.

    Assembled where the data exists (`repolish link` per config). One
    `LinkResult` per pass, paired with a section label ("Root",
    "Member: x", "Standalone"); both the link and copy summary trees are
    views of the same sections.

    `copies` is unfiltered — paused targets stay in it so the tree can
    mark them. `held_back` carries the destinations `apply_copies`
    actually skipped (partially paused directories list the individual
    files), and `paused_files` is the config's matcher input so a
    whole-target pause is detected even when nothing was held back.
    """

    symlinks: dict[str, list[ProviderSymlink]]
    copies: dict[str, list[ProviderCopy]]
    held_back: dict[str, list[str]]
    paused_files: frozenset[str]
