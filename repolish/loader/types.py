from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


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


class Providers(BaseModel):
    """Structured provider contributions collected from template modules.

    - context: merged cookiecutter context
    - anchors: merged anchors mapping
    - delete_files: list of Paths representing files to delete
    - file_mappings: dict mapping destination paths to source paths in template
    - create_only_files: list of Paths for files that should only be created if they don't exist
    """

    context: dict[str, object] = Field(default_factory=dict)
    anchors: dict[str, str] = Field(default_factory=dict)
    delete_files: list[Path] = Field(default_factory=list)
    file_mappings: dict[str, str] = Field(default_factory=dict)
    create_only_files: list[Path] = Field(default_factory=list)
    # provenance mapping: posix path -> list of Decision instances
    delete_history: dict[str, list[Decision]] = Field(default_factory=dict)


class Accumulators(BaseModel):
    """Internal accumulator used during two-phase provider merging.

    This mirrors the runtime mutable containers used by the orchestrator to
    collect anchors, file mappings, create-only sets, delete sets and the
    provenance history before converting to the public `Providers` model.
    """

    merged_anchors: dict[str, str]
    merged_file_mappings: dict[str, str]
    create_only_set: set[Path]
    delete_set: set[Path]
    history: dict[str, list[Decision]]
