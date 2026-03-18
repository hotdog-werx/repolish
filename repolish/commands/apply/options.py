from dataclasses import dataclass, field
from pathlib import Path

from repolish.loader.models import (
    BaseInputs,
    GlobalContext,
    ProviderEntry,
)


@dataclass
class ApplyOptions:
    """Parameters for the apply command (framework-agnostic)."""

    config_path: Path
    check_only: bool = False
    strict: bool = False
    global_context: GlobalContext | None = field(default=None, repr=False)
    extra_provider_entries: list[ProviderEntry] | None = field(
        default=None,
        repr=False,
    )
    extra_inputs: list[BaseInputs] | None = field(default=None, repr=False)


@dataclass
class ApplyCommandOptions:
    """Parameters for the apply command (framework-agnostic)."""

    config: Path
    check: bool = False
    strict: bool = False
    root_only: bool = False
    member: str | None = None
    standalone: bool = False


@dataclass
class MemberDryRunData:
    """Data collected from a single member's dry pass."""

    member_path: str
    """Repo-relative POSIX path to the member."""
    provider_entries: list[ProviderEntry] = field(default_factory=list)
    emitted_inputs: list[BaseInputs] = field(default_factory=list)
