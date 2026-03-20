from dataclasses import dataclass, field
from pathlib import Path

from repolish.config import ProviderSymlink, RepolishConfig
from repolish.providers.models import (
    BaseInputs,
    GlobalContext,
    ProviderEntry,
    SessionBundle,
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
class ResolvedSession:
    """The fully-resolved state of a single repolish session.

    Produced by running the provider pipeline (context creation → input
    exchange → finalization) without writing any files.  Captures everything
    needed to subsequently apply the session (staging → rendering → apply) or
    to pass cross-session data to a root session.

    Fields
    ------
    config_path:
        The ``repolish.yaml`` that was loaded.
    config:
        The resolved :class:`~repolish.config.RepolishConfig` for this session.
    global_context:
        The :class:`~repolish.providers.models.GlobalContext` injected into every
        provider, including the :class:`~repolish.providers.models.WorkspaceContext`.
    providers:
        All provider instances with their finalized contexts, file mappings,
        and template sources populated.
    aliases:
        Provider aliases in processing order.
    alias_to_pid:
        Maps each provider alias to its filesystem provider root path.
    pid_to_alias:
        Reverse map of ``alias_to_pid``.
    resolved_symlinks:
        Symlink declarations collected from all providers.
    extra_provider_entries:
        Provider entries contributed by member sessions (root pass only).
    extra_inputs:
        Inputs emitted by member sessions for cross-session routing (root pass
        only).
    """

    config_path: Path
    config: RepolishConfig = field(repr=False)
    global_context: GlobalContext = field(repr=False)
    providers: SessionBundle = field(repr=False)
    aliases: list[str] = field(default_factory=list)
    alias_to_pid: dict[str, str] = field(default_factory=dict, repr=False)
    pid_to_alias: dict[str, str] = field(default_factory=dict, repr=False)
    resolved_symlinks: dict[str, list[ProviderSymlink]] = field(
        default_factory=dict,
        repr=False,
    )
    extra_provider_entries: list[ProviderEntry] = field(
        default_factory=list,
        repr=False,
    )
    extra_inputs: list[BaseInputs] = field(default_factory=list, repr=False)
    provider_entries: list[ProviderEntry] = field(
        default_factory=list,
        repr=False,
    )
    """Provider entries emitted outward by this session (cross-session routing to root)."""
    emitted_inputs: list[BaseInputs] = field(default_factory=list, repr=False)
    """Inputs emitted outward by this session's providers (cross-session routing to root)."""
