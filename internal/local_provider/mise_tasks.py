"""Mise task discovery for the dev-tasks insertion.

Temporary home: the collection is repo-agnostic and moves to a shared
provider once a workspace provider can serve this insertion across repos.
Until then the local provider carries it.

Tasks follow the `provider:item` naming convention (`docs:build`,
`workspace:repolish:check`); a task with no `:` belongs to the repo
itself.
"""

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO_GROUP = 'repo'


@dataclass(frozen=True)
class MiseTask:
    """One task reported by mise."""

    name: str
    """The task name, run as `mise run <name>`."""

    description: str
    """One-line description; empty when the task declares none."""


@dataclass(frozen=True)
class TaskGroup:
    """The tasks of one owner, grouped by task-name prefix."""

    name: str
    """The provider prefix, or `repo` for tasks with no prefix."""

    tasks: list[MiseTask]


def _group_name(task_name: str) -> str:
    """Map a task name to its group: the `:` prefix, else the repo."""
    if ':' in task_name:
        return task_name.split(':', 1)[0]
    return REPO_GROUP


def collect_mise_tasks(root: Path) -> list[TaskGroup]:
    """Collect mise's own task list for *root*, grouped and ordered.

    Asking mise (instead of reading task files) stays correct no matter
    where tasks come from: this repo's files, imports, or tasks other
    providers contribute. The `repo` group comes first, remaining groups
    alphabetical, tasks within a group alphabetical.
    """
    mise_bin = shutil.which('mise')
    if mise_bin is None:
        msg = f'mise not found on PATH; cannot list tasks for {root}'
        raise RuntimeError(msg)
    proc = subprocess.run(  # noqa: S603 - fixed argv, binary resolved via shutil.which
        [mise_bin, 'task', 'ls', '--json'],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        msg = f'mise task ls --json failed in {root}: {proc.stderr.strip()}'
        raise RuntimeError(msg)
    entries = json.loads(proc.stdout)
    grouped: dict[str, list[MiseTask]] = {}
    for entry in entries:
        name = str(entry['name'])
        grouped.setdefault(_group_name(name), []).append(
            MiseTask(name=name, description=str(entry.get('description') or '')),
        )
    groups: list[TaskGroup] = []
    for group_name, tasks in grouped.items():
        tasks.sort(key=lambda task: task.name)
        groups.append(TaskGroup(name=group_name, tasks=tasks))
    groups.sort(key=lambda group: (group.name != REPO_GROUP, group.name))
    return groups
