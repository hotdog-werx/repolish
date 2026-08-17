"""File disposition models: per-file tracking, provider contributions, and build helpers.

Defines the types that track what happens to each file across all providers:
- :class:`Action` / :class:`Decision` — provenance enum and record
- :class:`FileMode` / :class:`TemplateMapping` / :class:`FileRecord` — per-file behaviour
- :class:`SessionBundle` — aggregate of all provider contributions
- :class:`Accumulators` — mutable workspace built up during provider loading
- :func:`build_file_records` — builds the unified disposition list after staging
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Generic, Literal, TypeAlias, TypeVar

from pydantic import BaseModel, Field

from repolish.providers.models.context import BaseContext
from repolish.providers.models.template_path import RepolishTemplatePath


class BaseProviderMethodOptions(BaseModel):
    """Base class for options controlling provider method behavior.

    Establishes a common contract for all provider methods that support
    user-configurable options. Subclasses add method-specific fields while
    inheriting the common enabled and priority controls.

    Attributes:
        enabled: Whether this method is active. When False the method's effect
            is ignored even if declared by the provider.
        priority: Integer priority for conflict resolution. Higher values win.
            Used when multiple providers contribute to the same target.
    """

    enabled: bool = True
    priority: int = 0


class FileMappingOptions(BaseProviderMethodOptions):
    """Options controlling the behavior of a single file_mapping entry.

    Provides fine-grained control over individual file mappings, allowing
    users to enable/disable specific mappings or control rendering behavior
    without modifying provider code.

    Attributes:
        skip_render: When True, the template is staged but Jinja rendering is
            skipped. Useful for templates that should only be used for anchor
            extraction or post-processing.
    """

    skip_render: bool = False


class FileValidatorOptions(BaseProviderMethodOptions):
    """Options controlling validator execution for a file or provider.

    The common `enabled` flag disables the whole validator set for a file when
    set to ``False``. `validators` lets a provider declare a named allow-list or
    deny-list for individual validators without requiring project-level override
    machinery.

    Example:
        FileValidatorOptions(
            enabled=True,
            validators={'lint': True, 'schema': False},
        )
    """

    validators: dict[str, bool] = Field(default_factory=dict)


class ValidationStatus(str, Enum):
    """Status used to classify the outcome of a validator."""

    PASS = 'pass'  # noqa: S105 - things can have a pass sir!!. Not everything is a password
    WARNING = 'warning'
    ERROR = 'error'


@dataclass(frozen=True)
class ValidationResult:
    """Result returned by a validator.

    Prefer ``status`` to a boolean ``passed`` flag so validators can distinguish
    between a clean pass, a warning, and an actual error.
    """

    status: ValidationStatus = ValidationStatus.PASS
    message: str = ''
    path: str = ''
    validator_name: str = ''

    def __init__(
        self,
        *,
        status: ValidationStatus | str = ValidationStatus.PASS,
        message: str = '',
        path: str = '',
        validator_name: str = '',
    ) -> None:
        """Normalize validator results to a typed status enum."""
        if isinstance(status, str):
            status = ValidationStatus(status.lower())
        object.__setattr__(self, 'status', status)
        object.__setattr__(self, 'message', message)
        object.__setattr__(self, 'path', path)
        object.__setattr__(self, 'validator_name', validator_name)


ContextT = TypeVar('ContextT', bound=BaseContext)


ValidatorFn: TypeAlias = Callable[[ContextT, Path], ValidationResult]
"""Function signature for a file validator.

The callable receives the provider's concrete context and the resolved path,
then returns a :class:`ValidationResult` describing whether validation passed and
any user-facing message.
"""


class FileValidatorSpec(BaseModel, Generic[ContextT]):
    """Concrete typed payload for a single validator registration.

    This is the public contract used by ``create_file_validators()`` so provider
    authors can express a validator as either a bare callable or a structured
    specification with per-validator options::

        {
            'config.toml': {
                'lint': validator_fn,
                'schema': {
                    'fn': validator_fn,
                    'options': FileValidatorOptions(enabled=True),
                },
            }
        }
    """

    fn: Callable[[ContextT, Path], ValidationResult]
    options: FileValidatorOptions = Field(default_factory=FileValidatorOptions)


FileValidatorEntry: TypeAlias = FileValidatorSpec[ContextT] | Callable[[ContextT, Path], ValidationResult]
"""One validator entry used in a file validator registry."""

ValidatorMapping: TypeAlias = dict[str, FileValidatorEntry[ContextT]]
"""All validators registered for a specific destination file."""

FileValidatorsForFile: TypeAlias = ValidatorMapping[ContextT]
"""Backward-compatible alias for validator entries on a single file."""

FileValidatorsByPath: TypeAlias = dict[str, ValidatorMapping[ContextT]]
"""Top-level map keyed by destination path."""

InsertionRenderer: TypeAlias = Callable[..., str]
"""Renderer callable used for an insertion block; must return the replacement text."""

InsertionRegistry: TypeAlias = dict[str, InsertionRenderer]
"""Function name → renderer callable for a single destination file."""

InsertionRegistryByPath: TypeAlias = dict[str, InsertionRegistry]
"""Top-level map keyed by destination path for insertion renderers."""


class Action(str, Enum):
    """Enumeration of possible actions for a path."""

    delete = 'delete'
    keep = 'keep'


class Decision(BaseModel):
    """Typed provenance decision recorded for each path.

    - source: provider identifier (POSIX string)
    - action: Action enum
    """

    source: str
    action: Action


class FileMode(str, Enum):
    """Per-file behavior for a `TemplateMapping`.

    - REGULAR: render and materialize as normal (default)
    - CREATE_ONLY: treat the destination as create-only (never overwrite existing)
    - DELETE: mark the destination for deletion (no source template required)
    - KEEP: explicitly cancel a delete scheduled by an earlier provider
    - SUPPRESS: skip staging and rendering for this file entirely; useful
      during development when a template is temporarily broken
    """

    REGULAR = 'regular'
    CREATE_ONLY = 'create_only'
    DELETE = 'delete'
    KEEP = 'keep'
    SUPPRESS = 'suppress'


@dataclass(frozen=True)
class TemplateMapping:
    """Typed representation for a per-file `file_mappings` entry.

    Fields:
      - source_template: relative path to the template under the merged template
        tree. May be 'None' for `FileMode.DELETE` mappings. This is the original
        template path used for display/provenance (e.g., in FileRecord.source).
      - extra_context: optional typed context (Pydantic models allowed).
      - file_mode: optional behavior hint for the destination path.
      - promote_conflict: conflict resolution strategy when two member sessions
        promote the same destination path via `promote_file_mappings`.  Only
        relevant for entries returned from `promote_file_mappings`; ignored for
        regular `create_file_mappings` entries.
        - ``"identical"`` — render both and assert byte-for-byte equality;
          fail loudly if they differ (default, safe for shared CI templates).
        - ``"last_wins"`` — last member session processed wins silently.
        - ``"error"`` — fail immediately on any conflict.
      - options: optional :class:`FileMappingOptions` controlling per-file
        behaviour (enabled, priority, skip_render).  When ``enabled=False``
        the mapping is suppressed by default; users can re-enable it via the
        project config ``overrides.file_mappings`` entry.
      - source_provider: provider alias that originally supplied the template.
        This is not something the provider needs to set; the loader populates
        it during merging so we can track provenance.
      - preprocessed_source: optional internal path to a preprocessed copy of
        the template. When set, this file is used for rendering instead of
        `source_template`. Used when one template maps to multiple destinations
        with different anchor content.

    The `source_template` path is wrapped in :class:`RepolishTemplatePath` internally,
    so the `.jinja` extension is handled transparently. Use the `template_path`
    property to access the wrapped path object. When `preprocessed_source` is set,
    use `resolve_effective_template_path` to get the actual file to render.
    """

    source_template: str | None
    extra_context: object | None = None
    file_mode: FileMode = FileMode.REGULAR
    promote_conflict: Literal['identical', 'last_wins', 'error'] = 'identical'
    options: FileMappingOptions | None = None
    # provider alias that originally supplied the template.  This is not
    # something the provider needs to set; the loader populates it during
    # merging so we can track provenance of conditional/create-only/delete
    # mappings across multiple providers.
    source_provider: str | None = None
    # Internal path to a preprocessed copy (set when one template maps to
    # multiple destinations with different anchor content).
    preprocessed_source: str | None = None
    # Internal cached template path wrapper (set in __post_init__)
    _template_path: RepolishTemplatePath | None = field(
        init=False,
        repr=False,
        default=None,
    )

    def __post_init__(self) -> None:
        """Initialize the wrapped template path."""
        # Use preprocessed_source if available, otherwise fall back to source_template
        effective_source = self.preprocessed_source or self.source_template
        if effective_source is not None:
            object.__setattr__(
                self,
                '_template_path',
                RepolishTemplatePath.from_string(effective_source),
            )

    @property
    def logical_name(self) -> str | None:
        """The logical destination name (without .jinja suffix)."""
        if self._template_path is None:
            return None
        return self._template_path.logical_name

    def resolve_template_path(self, template_dir: Path) -> Path:
        """Resolve the actual template file path on disk.

        After staging, source_template matches the file on disk exactly
        (without .jinja suffix). This method simply constructs the path
        and verifies it exists.

        Args:
            template_dir: Base directory to search for the template.

        Returns:
            The resolved Path to the template file.

        Raises:
            FileNotFoundError: If the template cannot be found.
        """
        # source_template should never be None when this is called, but guard
        # against malformed mappings. The caller should filter None mappings
        # before calling, so this branch is intentionally not covered.
        if self._template_path is None:  # pragma: no cover
            msg = 'source_template is None'
            raise FileNotFoundError(msg)

        # After staging, source_template matches disk exactly (no .jinja)
        resolved = template_dir / self._template_path.logical_name
        if not resolved.exists():
            msg = f'template not found: {resolved}'
            raise FileNotFoundError(msg)
        return resolved


def map_folder(
    dest_dir: str,
    source_dir: str,
    template_dir: Path,
    *,
    file_mode: FileMode = FileMode.REGULAR,
    extra_context: object | None = None,
) -> dict[str, str | TemplateMapping]:
    """Build ``create_file_mappings`` entries for every file in a ``_repolish.`` folder.

    Walks ``template_dir / source_dir`` and produces one mapping entry per file.
    Each destination key is ``dest_dir/<relative-path>`` and each source value
    is ``source_dir/<relative-path>``, where the relative path is taken from
    inside ``source_dir``.  The ``.jinja`` suffix is stripped from destination
    keys but preserved in source values (staging handles the stripping).

    This is a convenience helper for ``create_file_mappings`` when a whole
    subtree of templates belongs to one conditional variant.  The returned dict
    can be inspected and adjusted before being spread into the final mapping::

        def create_file_mappings(self, context):
            tpl = self.templates_root / 'repolish'
            if context.use_github:
                return map_folder('.github', '_repolish.ci.github', tpl)
            return map_folder('', '_repolish.ci.gitlab', tpl)

    Args:
        dest_dir: Destination directory prefix (e.g. ``'.github'``). Pass an
            empty string to map files directly to the project root.
        source_dir: Source directory under ``template_dir``, conventionally
            prefixed with ``_repolish.`` (e.g. ``'_repolish.ci.github'``).
        template_dir: Directory that contains ``source_dir``. For
            ``Provider``, pass ``self.templates_root / 'repolish'``. For
            ``ModeHandler``, pass ``self.templates_root``.
        file_mode: Mode applied to every produced entry. Defaults to
            ``FileMode.REGULAR``.
        extra_context: Optional context merged into every produced entry.

    Returns:
        A dict mapping destination paths to source paths. Entries are plain
        strings when both ``file_mode`` is ``REGULAR`` and ``extra_context``
        is ``None``; otherwise they are ``TemplateMapping`` instances.
    """
    source_path = template_dir / source_dir
    if not source_path.is_dir():
        return {}
    return {
        _dest_key(dest_dir, item, source_path): _source_val(
            source_dir,
            item,
            source_path,
            file_mode,
            extra_context,
        )
        for item in sorted(source_path.rglob('*'))
        if item.is_file()
    }


def _dest_key(dest_dir: str, item: Path, source_path: Path) -> str:
    rel = item.relative_to(source_path).as_posix()
    # Use RepolishTemplatePath to handle .jinja extension transparently
    dest_rel = RepolishTemplatePath.from_string(rel).logical_name
    return f'{dest_dir}/{dest_rel}' if dest_dir else dest_rel


def _source_val(
    source_dir: str,
    item: Path,
    source_path: Path,
    file_mode: FileMode,
    extra_context: object | None,
) -> str | TemplateMapping:
    rel = item.relative_to(source_path).as_posix()
    source = f'{source_dir}/{rel}'
    if file_mode is FileMode.REGULAR and extra_context is None:
        return source
    return TemplateMapping(
        source,
        extra_context=extra_context,
        file_mode=file_mode,
    )


@dataclass(frozen=True)
class FileRecord:
    """Resolved disposition for a single managed file.

    `path` is the POSIX destination path.
    `mode` is the effective FileMode (REGULAR, CREATE_ONLY, DELETE, KEEP).
    `owner` is the config alias of the provider that controls this file,
    or 'config' for entries driven by config.delete_files.
    `source` is the source template path for explicitly-mapped files, or
    None for auto-staged and deleted files.
    `overlay_dir` is the mode subdirectory (``'root'``, ``'member'``, or
    ``'standalone'``) when the file was staged from a mode overlay rather
    than the provider's base ``repolish/`` directory.  ``None`` for all
    other files.
    `promoted_from` is the member session name that contributed this file
    via ``promote_file_mappings``.  ``None`` for all non-promoted files.
    `overridden_by` is the provider alias that clobbered a promoted file
    via the root session's own ``create_file_mappings``.  ``None`` when
    the promoted file was written without conflict.
    """

    path: str
    mode: FileMode
    owner: str
    source: str | None = None
    overlay_dir: str | None = None
    promoted_from: str | None = None
    overridden_by: str | None = None


class SessionBundle(BaseModel):
    """All contributions collected from providers during one session run.

    Produced by the provider pipeline after all providers have been loaded,
    their contexts finalized, and their file mappings and anchors gathered.
    Passed to the hydration layer to stage templates, render them, and apply
    the results to the project.

    A single `SessionBundle` belongs to exactly one session (one directory
    context: standalone project, monorepo root, or monorepo package member).
    """

    anchors: dict[str, str] = Field(default_factory=dict)
    """Merged Jinja anchor definitions contributed by all providers."""
    delete_files: list[Path] = Field(default_factory=list)
    """Files that one or more providers have declared should be deleted."""
    file_mappings: dict[str, str | TemplateMapping] = Field(
        default_factory=dict,
    )
    """Destination path → source path or `TemplateMapping` for each managed file."""
    create_only_files: list[Path] = Field(default_factory=list)
    """Files that should only be created if they do not already exist."""
    delete_history: dict[str, list[Decision]] = Field(default_factory=dict)
    """Provenance of delete/keep decisions keyed by POSIX destination path."""
    provider_contexts: dict[str, BaseContext] = Field(
        default_factory=dict,
    )
    """Finalized typed context objects keyed by provider_id. Use these for
    per-provider template rendering — do not flatten into a plain dict."""
    template_sources: dict[str, str] = Field(default_factory=dict)
    """Relative template path (POSIX) → provider_id that staged the file.
    Populated during staging so the renderer can resolve `{{ _provider }}`."""
    suppressed_sources: set[str] = Field(default_factory=set)
    """Template paths explicitly suppressed via a `None` mapping in
    `create_file_mappings`; excluded from auto-staging."""
    disabled_file_mappings: dict[str, str] = Field(default_factory=dict)
    """Destination paths explicitly disabled via config overrides.
    Kept separate from `suppressed_sources` so they can be shown in the
    apply summary as a visible reason without triggering the paused warning
    path."""
    template_overlay_dirs: dict[str, str] = Field(default_factory=dict)
    """Relative template path → mode subdir name for files staged from a
    mode overlay directory (e.g. ``{'ci.yaml': 'root'}`` for a file that
    came from ``provider_root/root/`` rather than ``provider_root/repolish/``).
    Populated during staging, before ``build_file_records`` is called."""
    file_records: list[FileRecord] = Field(default_factory=list)
    """Unified file disposition list. Empty until `build_file_records` is called."""
    promoted_file_mappings: dict[str, str | TemplateMapping] = Field(
        default_factory=dict,
    )
    """Destination path → source template or TemplateMapping for files this
    session wants promoted to the repo root.  Collected from
    ``promote_file_mappings()`` on member providers; empty for root and
    standalone sessions."""
    paused_files: frozenset[str] = Field(default_factory=frozenset)
    """POSIX-style destination paths that repolish must not touch this run.
    Populated from ``config.paused_files`` at session setup time; analogous to
    ``suppressed_sources`` but driven by project config rather than provider
    declarations."""
    validator_sources: dict[str, str] = Field(default_factory=dict)
    """Destination path → provider id that contributed a validator for that file.
    Used to display validator-only files in the summary even when no
    ``create_file_mappings()`` entry exists for that destination."""
    file_validators: FileValidatorsByPath = Field(default_factory=dict)
    """Destination path → validator name → validator callable or validator config.
    Providers can register validation hooks via ``create_file_validators()``;
    the runner resolves the callables and executes them against the file on disk.
    """
    file_insertions: InsertionRegistryByPath = Field(default_factory=dict)
    """Destination path → insertion-function name → callable for file-local blocks.
    Providers can register insertion functions via ``create_file_insertions()``;
    the writer later resolves the function by the block metadata and writes the
    rendered content back into the file.
    """
    insertion_sources: dict[str, list[str]] = Field(default_factory=dict)
    """Destination path → list of provider ids that contributed an insertion registry.
    Used for summary/debug output when the same target file is updated by more than
    one provider in a monorepo or multi-provider session.
    """


def _records_from_template_sources(
    template_sources: dict[str, str],
    create_only_posix: set[str],
    pid_to_alias: dict[str, str],
    explicit_sources: set[str],
    overlay_dirs: dict[str, str] | None = None,
) -> dict[str, FileRecord]:
    """Return FileRecord entries from staged template sources.

    ``explicit_sources`` is the set of source paths claimed by
    ``create_file_mappings`` entries (both plain strings and
    ``TemplateMapping.source_template`` values).  These files are registered in
    ``template_sources`` so the renderer can look up the declaring provider's
    context (enabling ``{{ _provider }}`` access), but they are staging
    intermediates and must not appear in the file-records display.
    """
    files: dict[str, FileRecord] = {}
    for rel_path, pid in template_sources.items():
        if rel_path in explicit_sources:
            continue
        owner = pid_to_alias.get(pid, pid)
        mode = FileMode.CREATE_ONLY if rel_path in create_only_posix else FileMode.REGULAR
        overlay_dir = overlay_dirs.get(rel_path) if overlay_dirs else None
        files[rel_path] = FileRecord(
            path=rel_path,
            mode=mode,
            owner=owner,
            overlay_dir=overlay_dir,
        )
    return files


def _records_from_file_mappings(
    file_mappings: dict[str, str | TemplateMapping],
    pid_to_alias: dict[str, str],
) -> dict[str, FileRecord]:
    """Return FileRecord entries from explicit file_mappings."""
    files: dict[str, FileRecord] = {}
    for dest, src in file_mappings.items():
        if isinstance(src, TemplateMapping):
            raw_pid = src.source_provider or ''
            owner = pid_to_alias.get(raw_pid, raw_pid or 'unknown')
            files[dest] = FileRecord(
                path=dest,
                mode=src.file_mode,
                owner=owner,
                source=src.source_template,
            )
        else:
            files[dest] = FileRecord(
                path=dest,
                mode=FileMode.REGULAR,
                owner='unknown',
            )
    return files


def _records_from_delete_files(
    delete_files: list[Path],
    delete_history: dict[str, list[Decision]],
    pid_to_alias: dict[str, str],
    config_pid: str,
) -> dict[str, FileRecord]:
    """Return FileRecord entries for paths scheduled for deletion."""
    files: dict[str, FileRecord] = {}
    for rel in delete_files:
        path_str = rel.as_posix()
        decisions = delete_history.get(path_str, [])
        if decisions:
            last_src = decisions[-1].source
            owner = 'config' if last_src == config_pid else pid_to_alias.get(last_src, last_src)
        else:
            owner = 'unknown'
        files[path_str] = FileRecord(
            path=path_str,
            mode=FileMode.DELETE,
            owner=owner,
        )
    return files


def build_file_records(
    providers: SessionBundle,
    pid_to_alias: dict[str, str],
    config_pid: str,
) -> list[FileRecord]:
    """Build the unified file disposition list from all provider contributions.

    Call once after staging (when `template_sources` is populated).  The
    result is stored on `providers.file_records` so downstream helpers can
    read a single authoritative source instead of recombining multiple fields.

    Ownership rules:
    - regular/create_only: driven by `template_sources`
    - mapping modes: taken from `TemplateMapping.file_mode`
    - delete: last `Decision` in `delete_history`; source == config_pid -> owner 'config'
    """
    create_only_posix = {p.as_posix() for p in providers.create_only_files}
    # collect all source paths explicitly claimed by file_mappings so they can
    # be excluded from the auto-staged template records.  these paths are
    # registered in template_sources (for provider context lookup) but are not
    # standalone managed output files.
    explicit_sources: set[str] = set()
    for _src in providers.file_mappings.values():
        if isinstance(_src, str):
            explicit_sources.add(_src)
        elif isinstance(_src, TemplateMapping) and _src.source_template:
            explicit_sources.add(_src.source_template)
    files: dict[str, FileRecord] = {}
    files.update(
        _records_from_template_sources(
            providers.template_sources,
            create_only_posix,
            pid_to_alias,
            explicit_sources,
            providers.template_overlay_dirs or None,
        ),
    )
    files.update(
        _records_from_file_mappings(providers.file_mappings, pid_to_alias),
    )
    for dest, provider_id in providers.validator_sources.items():
        files.setdefault(
            dest,
            FileRecord(
                path=dest,
                mode=FileMode.REGULAR,
                owner=pid_to_alias.get(provider_id, provider_id or 'unknown'),
                source=None,
            ),
        )
    for dest, provider_ids in providers.insertion_sources.items():
        # Use the first provider as the primary owner for display purposes
        primary_provider_id = provider_ids[0] if provider_ids else 'unknown'
        files.setdefault(
            dest,
            FileRecord(
                path=dest,
                mode=FileMode.REGULAR,
                owner=pid_to_alias.get(
                    primary_provider_id,
                    primary_provider_id or 'unknown',
                ),
                source=None,
            ),
        )
    for dest, provider_id in providers.disabled_file_mappings.items():
        files[dest] = FileRecord(
            path=dest,
            mode=FileMode.SUPPRESS,
            owner=pid_to_alias.get(provider_id, provider_id or 'unknown'),
            source=None,
        )
    files.update(
        _records_from_delete_files(
            providers.delete_files,
            providers.delete_history,
            pid_to_alias,
            config_pid,
        ),
    )
    return sorted(files.values(), key=lambda r: r.path)


@dataclass
class Accumulators:
    """Mutable workspace used while collecting contributions from all providers.

    `collect_provider_contributions` iterates over every loaded provider,
    calls `create_anchors` and `create_file_mappings`, and accumulates the
    results here.  The fields are written into a `SessionBundle` instance once
    collection is complete.

    `merged_anchors` aggregates the per-provider anchor dicts: each call to
    `create_anchors()` can contribute new keys; later providers win on
    conflicts.  All fields default to empty so callers can construct with
    `Accumulators()`.
    """

    merged_anchors: dict[str, str] = field(default_factory=dict)
    merged_file_mappings: dict[str, str | TemplateMapping] = field(
        default_factory=dict,
    )
    create_only_set: set[Path] = field(default_factory=set)
    delete_set: set[Path] = field(default_factory=set)
    history: dict[str, list[Decision]] = field(default_factory=dict)
    # destination paths that providers explicitly mapped to None — these
    # should not be auto-staged even though no file_mappings entry exists.
    suppressed_sources: set[str] = field(default_factory=set)
    # destination paths explicitly disabled by config overrides; kept separate
    # so they can appear in the summary as disabled rather than paused.
    disabled_file_mappings: dict[str, str] = field(default_factory=dict)
    # Destination path → validator name → validator callable/config collected from
    # create_file_validators().
    file_validators: FileValidatorsByPath = field(default_factory=dict)
    # Destination path → provider id for validator-only registrations that do not
    # also appear in a file_mappings entry.
    validator_sources: dict[str, str] = field(default_factory=dict)
    # Destination path → insertion function name → callable collected from
    # create_file_insertions(). This is additive and mode-aware, so each active
    # provider contributes only the functions valid in its current workspace mode.
    file_insertions: InsertionRegistryByPath = field(default_factory=dict)
    insertion_sources: dict[str, list[str]] = field(default_factory=dict)
    # promoted_file_mappings: collected from promote_file_mappings() on member
    # providers; keyed by destination path relative to the repo root.
    promoted_file_mappings: dict[str, str | TemplateMapping] = field(
        default_factory=dict,
    )
