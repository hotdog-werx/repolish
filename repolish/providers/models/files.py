"""File disposition models: per-file tracking, provider contributions, and build helpers.

Defines the types that track what happens to each file across all providers:
- :class:`Action` / :class:`Decision` — provenance enum and record
- :class:`FileMode` / :class:`TemplateMapping` / :class:`FileRecord` — per-file behaviour
- :class:`SessionBundle` — aggregate of all provider contributions
- :class:`Accumulators` — mutable workspace built up during provider loading
- :func:`build_file_records` — builds the unified disposition list after staging
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path  # noqa: TC003 - Pydantic model fields require runtime resolution

from pydantic import BaseModel, Field

from repolish.providers.models.context import (
    BaseContext,  # noqa: TC001 - Pydantic model field requires runtime resolution
)


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
    """

    REGULAR = 'regular'
    CREATE_ONLY = 'create_only'
    DELETE = 'delete'
    KEEP = 'keep'


@dataclass(frozen=True)
class TemplateMapping:
    """Typed representation for a per-file `file_mappings` entry.

    Fields:
      - source_template: relative path to the template under the merged template
        tree. May be 'None' for `FileMode.DELETE` mappings.
      - extra_context: optional typed context (Pydantic models allowed).
      - file_mode: optional behavior hint for the destination path.
    """

    source_template: str | None
    extra_context: object | None = None
    file_mode: FileMode = FileMode.REGULAR
    # provider alias that originally supplied the template.  This is not
    # something the provider needs to set; the loader populates it during
    # merging so we can track provenance of conditional/create-only/delete
    # mappings across multiple providers.
    source_provider: str | None = None


@dataclass(frozen=True)
class FileRecord:
    """Resolved disposition for a single managed file.

    `path` is the POSIX destination path.
    `mode` is the effective FileMode (REGULAR, CREATE_ONLY, DELETE, KEEP).
    `owner` is the config alias of the provider that controls this file,
    or 'config' for entries driven by config.delete_files.
    `source` is the source template path for explicitly-mapped files, or
    None for auto-staged and deleted files.
    """

    path: str
    mode: FileMode
    owner: str
    source: str | None = None


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
    file_records: list[FileRecord] = Field(default_factory=list)
    """Unified file disposition list. Empty until `build_file_records` is called."""


def _records_from_template_sources(
    template_sources: dict[str, str],
    create_only_posix: set[str],
    pid_to_alias: dict[str, str],
    explicit_sources: set[str],
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
        files[rel_path] = FileRecord(path=rel_path, mode=mode, owner=owner)
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
        ),
    )
    files.update(
        _records_from_file_mappings(providers.file_mappings, pid_to_alias),
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
