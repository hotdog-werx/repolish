"""End-to-end provider testing: run the real apply pipeline against a fixture project.

Where :class:`~repolish.testing.ProviderTestBed` exercises provider hooks in
isolation, this module runs the production pipeline — staging, preprocessing,
rendering, insertions, post-process, apply, validators — against a made-up
project directory. Provider authors check in a fixture of their repo
(simplified), point the harness at a copy of it, and assert on the resulting
project tree, so provider behaviour is observable without touching a real
repository.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeVar

import yaml
from pydantic import BaseModel

from repolish.commands.apply.options import ApplyOptions
from repolish.commands.apply.pipeline import resolve_session
from repolish.commands.apply.session import apply_session
from repolish.fastlane.config import prepare_lane_config
from repolish.providers.models.context import (
    BaseContext,
    GithubRepo,
    GlobalContext,
)
from repolish.providers.models.workspace import WorkspaceContext
from repolish.testing._testbed import _locate_templates_root

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from repolish.commands.apply.options import (
        InsertionFileResult,
        ResolvedSession,
    )
    from repolish.providers.models import ValidationResult
    from repolish.providers.models.context import BaseInputs
    from repolish.providers.models.provider import Provider

CtxT = TypeVar('CtxT', bound=BaseContext)
InpT = TypeVar('InpT', bound=BaseModel)

_IGNORED_DIRS = frozenset({'.repolish', '.git', '__pycache__'})
_IGNORED_FILES = frozenset({'repolish.yaml'})
_IGNORED_SUFFIXES = frozenset({'.pyc'})


@dataclass(frozen=True)
class ApplyResult:
    """Outcome of one :func:`apply_provider` run.

    The underlying :class:`~repolish.commands.apply.options.ResolvedSession`
    carries everything the pipeline collected; the properties here are the
    commonly asserted views over it.
    """

    exit_code: int
    session: ResolvedSession = field(repr=False)
    project_dir: Path

    @property
    def apply_result(self) -> dict[str, str]:
        """Per-file apply status: ``'written'``, ``'unchanged'``, ``'deleted'``."""
        return self.session.apply_result

    @property
    def validation_results(self) -> dict[str, dict[str, ValidationResult]]:
        """Per-file per-validator results, keyed by destination path."""
        return self.session.validation_results

    @property
    def insertion_results(self) -> dict[str, InsertionFileResult]:
        """Per-file insertion execution summaries, keyed by destination path."""
        return self.session.insertion_results

    @property
    def emitted_inputs(self) -> list[BaseInputs]:
        """Inputs the run's providers emitted for other providers to receive.

        Recorded before any local routing, so a provider consuming its own
        output does not hide what it sent. Assert on the payloads to verify
        what a provider hands its peers.
        """
        return self.session.emitted_inputs

    @property
    def render_tree(self) -> Path:
        """The staged render tree the pipeline produced (open it to debug)."""
        return self.project_dir / '.repolish' / '_' / 'render' / 'repolish'

    def project_files(self) -> dict[str, str]:
        """Return ``{rel_path: content}`` for the applied project tree.

        Scratch directories (``.repolish/``, ``.git/``, ``__pycache__/`` at any
        depth), byte-compiled ``*.pyc`` files, and the harness-written
        ``repolish.yaml`` are excluded, so the result feeds
        :func:`~repolish.testing.assert_snapshots` directly and reflects only
        the fixture state plus what the provider wrote. Python tooling invoked
        by ``post_process`` can leave ``__pycache__`` directories behind; they
        are build junk, not project output.
        """
        files: dict[str, str] = {}
        for path in sorted(self.project_dir.rglob('*')):
            if not path.is_file():
                continue
            rel = path.relative_to(self.project_dir)
            if rel.as_posix() in _IGNORED_FILES:
                continue
            if any(part in _IGNORED_DIRS for part in rel.parts):
                continue
            if rel.suffix in _IGNORED_SUFFIXES:
                continue
            files[rel.as_posix()] = path.read_text(encoding='utf-8')
        return files

    def managed_files(self) -> dict[str, str]:
        """Return ``{rel_path: content}`` for exactly the files this run handled.

        The file set comes from the run's own records, not from a directory
        walk: every file the pipeline applied (``session.apply_result``, so
        template output and post-process output, minus deletions), every
        insertion target it staged (``session.insertion_results``, which the
        insertion pass applies outside ``apply_result``), plus every resource
        copy materialised on disk (minus paused targets). Build junk such as
        ``__pycache__/`` cannot appear because the session never lists it, and
        fixture files the run did not touch are absent because they are
        checked in with the fixture.

        Prefer this over :meth:`project_files` for snapshots: it is immune to
        stray files by construction. Symlink targets are not included (they
        are links into provider resources, not content). In ``check_only``
        runs nothing is written, so files recorded as applied are absent.
        """
        files: dict[str, str] = {}
        for dest, status in self.session.apply_result.items():
            if status not in ('written', 'unchanged'):
                continue
            files[dest] = (self.project_dir / dest).read_text(encoding='utf-8')
        for dest in self.session.insertion_results:
            path = self.project_dir / dest
            if path.is_file():
                files[dest] = path.read_text(encoding='utf-8')
        self._record_copies(files)
        return files

    def _record_copies(self, files: dict[str, str]) -> None:
        """Add materialised, unpaused copy targets to *files* in place."""
        paused = {target for targets in self.session.paused_copies.values() for target in targets}
        for copies in self.session.resolved_copies.values():
            for copy in copies:
                target = copy.target.as_posix()
                if target in paused:
                    continue
                path = self.project_dir / target
                if path.is_file():
                    files[target] = path.read_text(encoding='utf-8')


def stage_project(
    fixture_dir: Path,
    dest: Path,
    *,
    git_init: bool = False,
    owner: str = 'test-owner',
    repo: str = 'test-repo',
) -> Path:
    """Copy a checked-in fixture repo to *dest* and return the project path.

    Use this to stage a fixture directory (developer-owned files, insertion
    markers, values for ``repolish-regex`` capture — the simplified state of
    a real repo) into a writable per-test location. *dest* is the full target
    path (its parent must exist; *dest* itself must not). With ``git_init=True``
    a minimal git repository is initialised with an ``origin`` remote so
    git-dependent provider code sees the same environment as a real checkout.
    """
    shutil.copytree(fixture_dir, dest)
    if git_init:
        _init_git_repo(dest, owner=owner, repo=repo)
    return dest


def _init_git_repo(path: Path, *, owner: str, repo: str) -> None:
    """Initialise a bare-minimum git repo with an ``origin`` GitHub URL."""
    try:
        subprocess.run(
            ['git', 'init', '--initial-branch=main'],  # noqa: S607 - git resolved from PATH, fixed args
            cwd=str(path),
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:  # pragma: no cover - older git
        subprocess.run(
            ['git', 'init'],  # noqa: S607 - git resolved from PATH, fixed args
            cwd=str(path),
            check=True,
            capture_output=True,
        )
    subprocess.run(
        ['git', 'config', 'user.email', 'test@example.com'],  # noqa: S607 - git resolved from PATH, fixed args
        cwd=str(path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ['git', 'config', 'user.name', 'Test User'],  # noqa: S607 - git resolved from PATH, fixed args
        cwd=str(path),
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603 - owner/repo come from the harness, never user input
        [  # noqa: S607 - git resolved from PATH, fixed args
            'git',
            'remote',
            'add',
            'origin',
            f'https://github.com/{owner}/{repo}.git',
        ],
        cwd=str(path),
        check=True,
        capture_output=True,
    )


def apply_provider(  # noqa: PLR0913 - mirrors ApplyOptions on purpose
    provider_class: type[Provider[CtxT, InpT]],
    project_dir: Path,
    *,
    alias: str = 'test-provider',
    check_only: bool = False,
    skip_post_process: bool = False,
    fail_on_warnings: bool = False,
    config: Mapping[str, Any] | None = None,
    extra_inputs: Sequence[BaseInputs] | None = None,
    repo_owner: str = 'test-owner',
    repo_name: str = 'test-repo',
    year: int | None = None,
) -> ApplyResult:
    """Run the real ``repolish apply`` pipeline for *provider_class* in *project_dir*.

    The fixture project is exercised exactly as ``repolish apply`` runs it —
    staging, preprocessing, rendering, insertions, post-process, apply, and
    validators all execute against *project_dir* — with one difference: the
    ``repolish.yaml`` is written by the harness, pointing the configured alias
    at the provider package found from *provider_class*. Provider registration
    is written from that path (no link CLI, no installed wheel), with
    ``resources_dir`` set to the package's resources root (the parent of the
    templates directory), so copies and symlinks resolve their sources exactly
    as a linked provider's registration would.

    Args:
        provider_class: The concrete ``Provider`` subclass to test. Its
            ``repolish.py`` and ``repolish/`` templates are located by walking
            up from the class's module, so the class must come from a real
            provider package on disk.
        project_dir: The (writable) fixture project directory. A
            ``repolish.yaml`` is written into it and ``.repolish/`` scratch
            space is created during the run.
        alias: The provider alias used in the written config.
        check_only: Run ``apply --check`` instead: compare without writing and
            exit with ``2`` when there is drift.
        skip_post_process: Skip configured ``post_process`` commands.
        fail_on_warnings: Exit non-zero when validators report warnings.
        config: Additional ``repolish.yaml`` keys (``post_process``,
            ``paused_files``, ``delete_files``, provider ``overrides``, ...)
            merged into the written config. Provider entries under
            ``providers`` other than *alias* are kept, so a test can register
            peer providers for two-provider runs; the harness's entry for
            *alias* always wins.
        extra_inputs: Payloads delivered to this run's providers before
            finalization, exactly as a peer provider's outputs would be.
            Routing matches by schema (``get_inputs_schema``), so inject the
            provider's expected inputs model to test dependency handling
            without the peer provider installed.
        repo_owner: Owner for the injected ``repolish.repo`` context values —
            fixed by default so runs are deterministic without a git repo.
        repo_name: Repository name for the injected context values.
        year: Year exposed as ``repolish.year``. Defaults to the current year,
            matching production; pass an explicit value to freeze snapshots.

    Returns:
        An :class:`ApplyResult` with the exit code and the resolved session.
    """
    provider_root = _locate_templates_root(provider_class)
    config_data: dict[str, Any] = dict(config) if config else {}
    # Provider entries from `config` are kept so a test can register peer
    # providers (two-provider runs, read-pattern context access); only the
    # harness's own alias is forced, so it always wins.
    providers_config: dict[str, Any] = dict(config_data.get('providers') or {})
    # `_locate_templates_root` only ever finds `<pkg>/resources/templates`, so
    # its parent is the resources root the linker CLI would register. Copies
    # and symlinks resolve their sources against `resources_dir`; leaving it
    # unset would default it to the templates directory and break them.
    providers_config[alias] = {
        'provider_root': str(provider_root),
        'resources_dir': str(provider_root.parent),
    }
    config_data['providers'] = providers_config
    config_path = project_dir / 'repolish.yaml'
    config_path.write_text(yaml.safe_dump(config_data), encoding='utf-8')

    global_context = GlobalContext(
        repo=GithubRepo(owner=repo_owner, name=repo_name),
        year=year if year is not None else datetime.now(UTC).year,
        workspace=WorkspaceContext(mode='standalone', root_dir=project_dir),
    )
    options = ApplyOptions(
        config_path=config_path,
        check_only=check_only,
        skip_post_process=skip_post_process,
        fail_on_warnings=fail_on_warnings,
        global_context=global_context,
        extra_inputs=list(extra_inputs) if extra_inputs else None,
    )
    # `repolish apply` runs as a CLI with the project as the working directory;
    # resource copies and symlinks anchor their targets to the cwd. Run the
    # pipeline the same way so relative targets land inside *project_dir*.
    with contextlib.chdir(project_dir):
        session = resolve_session(options)
        exit_code = apply_session(
            session,
            check_only=check_only,
            skip_post_process=skip_post_process,
            fail_on_warnings=fail_on_warnings,
        )
    return ApplyResult(
        exit_code=exit_code,
        session=session,
        project_dir=project_dir,
    )


def apply_fast_lane(  # noqa: PLR0913 - mirrors apply_provider on purpose
    provider_class: type[Provider[CtxT, InpT]],
    project_dir: Path,
    lane: str,
    *,
    alias: str = 'test-provider',
    check_only: bool = False,
    skip_post_process: bool = False,
    fail_on_warnings: bool = False,
    config: Mapping[str, Any] | None = None,
    repo_owner: str = 'test-owner',
    repo_name: str = 'test-repo',
    year: int | None = None,
) -> ApplyResult:
    """Run the real fast-lane pipeline for *provider_class* in *project_dir*.

    This is the lane-specific sibling of :func:`apply_provider`. It prepares the
    same single-provider lane config the generated fast-lane CLI uses, then runs
    the real apply session restricted to *lane* against the fixture project.

    Use this when a provider author wants fixture-based assertions over lane
    output without shelling out through the CLI wrapper.
    """
    provider_root = _locate_templates_root(provider_class)
    config_data: dict[str, Any] = dict(config) if config else {}
    providers_config: dict[str, Any] = dict(config_data.get('providers') or {})
    providers_config[alias] = {
        'provider_root': str(provider_root),
        'resources_dir': str(provider_root.parent),
    }
    config_data['providers'] = providers_config
    config_path = project_dir / 'repolish.yaml'
    config_path.write_text(yaml.safe_dump(config_data), encoding='utf-8')

    global_context = GlobalContext(
        repo=GithubRepo(owner=repo_owner, name=repo_name),
        year=year if year is not None else datetime.now(UTC).year,
        workspace=WorkspaceContext(mode='standalone', root_dir=project_dir),
    )
    prepared = prepare_lane_config(
        provider_root,
        lane,
        cli_name=f'{alias}-cli',
        alias=alias,
        config_path=config_path,
    )
    options = ApplyOptions(
        config_path=config_path,
        check_only=check_only,
        skip_post_process=skip_post_process,
        fail_on_warnings=fail_on_warnings,
        provider_filter=[alias],
        global_context=global_context,
        lane=lane,
        lane_config=prepared,
        skip_dry_pass=True,
    )
    with contextlib.chdir(project_dir):
        session = resolve_session(options)
        exit_code = apply_session(
            session,
            check_only=check_only,
            skip_post_process=skip_post_process,
            fail_on_warnings=fail_on_warnings,
        )
    return ApplyResult(
        exit_code=exit_code,
        session=session,
        project_dir=project_dir,
    )


def assert_idempotent(  # noqa: PLR0913 - mirrors apply_provider on purpose
    provider_class: type[Provider[CtxT, InpT]],
    project_dir: Path,
    *,
    alias: str = 'test-provider',
    skip_post_process: bool = False,
    fail_on_warnings: bool = False,
    config: Mapping[str, Any] | None = None,
    extra_inputs: Sequence[BaseInputs] | None = None,
    repo_owner: str = 'test-owner',
    repo_name: str = 'test-repo',
    year: int | None = None,
) -> None:
    """Assert that applying *provider_class* to *project_dir* leaves no drift.

    Runs :func:`apply_provider`, then runs it again in check mode: the second
    run must exit ``0`` (a check after apply compares the project against the
    freshly rendered tree, so any non-zero result means the provider produces
    output it can't reproduce — the classic spurious-drift bug).

    Takes the same keyword arguments as :func:`apply_provider`, except
    ``check_only``.
    """
    result = apply_provider(
        provider_class,
        project_dir,
        alias=alias,
        skip_post_process=skip_post_process,
        fail_on_warnings=fail_on_warnings,
        config=config,
        extra_inputs=extra_inputs,
        repo_owner=repo_owner,
        repo_name=repo_name,
        year=year,
    )
    if result.exit_code != 0:
        msg = f'apply failed with exit code {result.exit_code}'
        raise AssertionError(msg)
    check = apply_provider(
        provider_class,
        project_dir,
        alias=alias,
        skip_post_process=skip_post_process,
        fail_on_warnings=fail_on_warnings,
        config=config,
        extra_inputs=extra_inputs,
        repo_owner=repo_owner,
        repo_name=repo_name,
        year=year,
        check_only=True,
    )
    if check.exit_code != 0:
        msg = f'check after apply reported drift (exit code {check.exit_code})'
        raise AssertionError(msg)
