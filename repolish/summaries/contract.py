"""The input contract: what a finished run hands to summaries.

`SummarySession` is a structural protocol, so the apply pipeline's
`ResolvedSession` satisfies it without wrapping or conversion — but the
dependency arrow stays honest: the pipeline *delivers* something that
matches what summaries asks for; summaries never imports the pipeline at
runtime. The member list below is the complete set of fields derivation
reads, annotated verbatim to match the delivered model, so adding a field
to the contract is a deliberate act ty verifies at every call site.

Hold-back kinds derivation must keep distinct (never collapse them):
`config.paused_files` is the loud, temporary escape hatch (the run logs
`files_paused` every time), while provider `None` mappings (SUPPRESSED)
and `overrides.file_mappings: false` (DISABLED) are silent.
"""

from __future__ import annotations

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
    """What summaries receives once a run has finished."""

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
