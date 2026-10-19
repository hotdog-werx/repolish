"""Scoped post_process entries: the command/files mapping form.

A scoped entry runs only when the run generated a file matching one of its
``files`` patterns (the shared paused_files pattern language); otherwise it
is recorded as ``skipped`` and never started. Plain strings and argv lists
keep their always-run meaning.
"""

import sys
from pathlib import Path

import pytest
from hotlog import configure_logging, resolve_verbosity
from pydantic import ValidationError

from repolish.postprocess import runner
from repolish.postprocess.models import PostProcessEntry
from repolish.utils import run_post_process


def _touch(target: Path) -> list[str]:
    """Build a command that creates *target*, proving the command ran."""
    return [
        sys.executable,
        '-c',
        f'from pathlib import Path; Path({str(target)!r}).touch()',
    ]


def test_normalize_entry_leaves_plain_commands_unscoped() -> None:
    assert runner._normalize_entry('ruff format .') == (
        ('ruff', 'format', '.'),
        None,
    )
    assert runner._normalize_entry(['ruff', 'format']) == (
        ('ruff', 'format'),
        None,
    )


def test_normalize_entry_carries_the_mapping_scope() -> None:
    entry = PostProcessEntry(command=['dprint', 'fmt'], files=['*.md', 'docs'])
    assert runner._normalize_entry(entry) == (
        ('dprint', 'fmt'),
        ('*.md', 'docs'),
    )


def test_scoped_command_runs_when_a_generated_file_matches(
    tmp_path: Path,
) -> None:
    configure_logging(verbosity=resolve_verbosity(verbose=0))
    ran = tmp_path / 'ran.txt'
    run = run_post_process(
        [PostProcessEntry(command=_touch(ran), files=['*.py'])],
        tmp_path,
        tmp_path,
        generated_files=['src/app.py', 'docs/guide.md'],
    )
    assert not run.failed
    assert ran.exists()
    outcome = run.outcomes[0]
    assert outcome.status == 'ok'
    assert outcome.scope == ('*.py',)


def test_scoped_command_skipped_when_no_file_matches(tmp_path: Path) -> None:
    configure_logging(verbosity=resolve_verbosity(verbose=0))
    never = tmp_path / 'never.txt'
    run = run_post_process(
        [PostProcessEntry(command=_touch(never), files=['*.md'])],
        tmp_path,
        tmp_path,
        generated_files=['src/app.py'],
    )
    assert not run.failed
    assert not never.exists()
    outcome = run.outcomes[0]
    assert outcome.status == 'skipped'
    assert outcome.scope == ('*.md',)
    assert outcome.returncode is None


def test_scope_matches_exact_directory_and_dotfile_forms(
    tmp_path: Path,
) -> None:
    """All three pattern-language forms scope: exact, directory, glob.

    The dotfile case is the one an "extensions" model cannot express:
    ``.prettierrc`` has no extension, but an exact path entry matches it.
    """
    configure_logging(verbosity=resolve_verbosity(verbose=0))
    exact_ran = tmp_path / 'exact.txt'
    dir_ran = tmp_path / 'dir.txt'
    never = tmp_path / 'never.txt'
    commands = [
        PostProcessEntry(command=_touch(exact_ran), files=['.prettierrc']),
        PostProcessEntry(command=_touch(dir_ran), files=['docs']),
        PostProcessEntry(command=_touch(never), files=['*.java']),
    ]
    run = run_post_process(
        commands,
        tmp_path,
        tmp_path,
        generated_files=['.prettierrc', 'docs/guide.md', 'src/app.py'],
    )
    assert [o.status for o in run.outcomes] == ['ok', 'ok', 'skipped']
    assert exact_ran.exists()
    assert dir_ran.exists()
    assert not never.exists()


def test_generated_files_none_runs_scoped_entries(tmp_path: Path) -> None:
    """No file set on offer: scoped entries run rather than silently skip."""
    configure_logging(verbosity=resolve_verbosity(verbose=0))
    ran = tmp_path / 'ran.txt'
    run = run_post_process(
        [PostProcessEntry(command=_touch(ran), files=['*.py'])],
        tmp_path,
        tmp_path,
    )
    assert run.outcomes[0].status == 'ok'
    assert ran.exists()


def test_unknown_placeholder_in_scoped_command_fails_up_front(
    tmp_path: Path,
) -> None:
    """Placeholders resolve before the loop, scoped entries included."""
    never = tmp_path / 'never.txt'
    with pytest.raises(ValueError, match='renderdir'):
        run_post_process(
            [
                PostProcessEntry(
                    command=['ruff', 'format', '{renderdir}'],
                    files=['*.py'],
                ),
                _touch(never),
            ],
            tmp_path,
            tmp_path,
            generated_files=['src/app.py'],
        )
    assert not never.exists()


def test_scoped_command_after_failure_is_not_run(tmp_path: Path) -> None:
    """Failure semantics dominate: a scoped command after a failure is not_run."""
    configure_logging(verbosity=resolve_verbosity(verbose=0))
    never = tmp_path / 'never.txt'
    run = run_post_process(
        [
            [sys.executable, '-c', 'import sys; sys.exit(1)'],
            PostProcessEntry(command=_touch(never), files=['*.py']),
        ],
        tmp_path,
        tmp_path,
        generated_files=['src/app.py'],
    )
    assert run.failed
    assert run.outcomes[1].status == 'not_run'
    assert not never.exists()


def test_entry_files_required_and_non_empty() -> None:
    """The mapping form exists to declare a scope: absent or empty is a config error."""
    with pytest.raises(ValidationError, match='files'):
        # model_validate: the omission is the point, not a constructor typo
        PostProcessEntry.model_validate({'command': 'dprint fmt'})
    with pytest.raises(ValidationError, match='files'):
        PostProcessEntry.model_validate({'command': 'dprint fmt', 'files': []})


def test_entry_accepts_string_command() -> None:
    entry = PostProcessEntry(
        command='dprint --config {config_dir}/dprint.json fmt',
        files=['*.json'],
    )
    assert runner._normalize_entry(entry) == (
        ('dprint', '--config', '{config_dir}/dprint.json', 'fmt'),
        ('*.json',),
    )
