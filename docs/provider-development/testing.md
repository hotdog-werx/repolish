# Testing Providers

The `repolish.testing` module gives provider authors a lightweight harness for
exercising provider hooks without a full CLI pipeline, git repo, or installed
wheels. Import it directly in your test suite:

```python
from repolish.testing import (
    ProviderTestBed,
    SnapshotRunOptions,
    run_snapshot_case,
    include_paths,
    exclude_paths,
    assert_snapshots,
    make_context,
)
```

---

## Quick Start: End-to-End Fixture Testing (Recommended)

The most faithful way to test a provider is to run the **real `repolish apply`
pipeline** against a made-up project and assert on what it produces:
`apply_provider()` stages, preprocesses, renders, inserts, post-processes,
applies, and validates: everything `repolish apply` does, with one difference:
the `repolish.yaml` is written by the harness, pointing at your provider
package. No link CLI, no installed wheels, no real repository.

Resource copies and symlinks work as in production: the harness registers
`resources_dir` at the package's `resources/` root (the parent of the templates
directory), which is what the provider's link CLI records, so sources outside
the templates tree resolve correctly. The run is also anchored to the project
directory, so relative copy and symlink targets land inside the fixture, not
your test process's working directory.

The made-up project is a **fixture**: a checked-in directory holding the
simplified state of a repo you want to simulate: developer-owned files,
insertion markers, values for `repolish-regex` capture, an old config file your
provider is about to delete. Stage it into a per-test copy, apply, and assert or
snapshot the result:

```python
from pathlib import Path

from repolish.testing import (
    apply_fast_lane,
    apply_provider,
    assert_idempotent,
    assert_snapshots,
    stage_project,
)

from my_provider.resources.templates.repolish import MyProvider

FIXTURES = Path(__file__).parent / 'fixtures'
SNAPSHOT_DIR = Path(__file__).parent / 'snapshots' / 'my_provider'


def test_full_apply(tmp_path: Path) -> None:
    project = stage_project(FIXTURES / 'my-repo', tmp_path / 'project')

    result = apply_provider(MyProvider, project)

    assert result.exit_code == 0
    assert result.apply_result['README.md'] == 'written'
    assert_snapshots(result.managed_files(), SNAPSHOT_DIR)
```

### Testing fast lanes end to end

The same fixture pattern works for named fast lanes. Use `apply_fast_lane()`
when you want the real lane runtime, but you do not want to shell out through
the generated provider CLI in every test.

```python
from pathlib import Path

from repolish.testing import (
    apply_fast_lane,
    assert_snapshots,
    include_paths,
    stage_project,
)


def test_actions_lane(tmp_path: Path) -> None:
    project = stage_project(FIXTURES / 'my-repo', tmp_path / 'project')

    result = apply_fast_lane(MyProvider, project, 'actions')
    lane_files = include_paths(result.managed_files(), exact={'action.yaml'})

    assert result.exit_code == 0
    assert_snapshots(lane_files, SNAPSHOT_DIR / 'actions')
```

This is useful when a lane generates templates through the normal repolish
pipeline and you want the same fixture-and-snapshot ergonomics as full apply
tests. The helper exercises the real lane restriction path, so regular provider
hooks stay out of the run and lane-specific post-process behavior is honored. If
the provider also auto-stages other managed files in the same fixture, filter
the result down to the lane-owned paths before snapshotting.

Two views over the result, both `{rel_path: content}` and both ready for
`assert_snapshots`:

- `result.managed_files()` is the one to snapshot: exactly the files this run
  applied, staged insertions into, or copied, taken from the run's own records
  (`apply_result`, `insertion_results`, `resolved_copies`). Because the file set
  comes from the session rather than a directory walk, nothing can leak in: no
  `__pycache__/`, no `*.pyc`, no exclusion list to maintain. Untouched fixture
  files are absent; they are checked in with the fixture.
- `result.project_files()` is the whole applied project tree (fixture state plus
  provider output) when you also want to assert the surrounding project: scratch
  dirs (`.repolish/`, `.git/`, `__pycache__/` at any depth), `*.pyc` files, and
  the harness-written `repolish.yaml` are excluded. Byte caches left behind by
  `post_process` commands that invoke python are build junk, not project output.

Both return plain dicts, so `include_paths` / `exclude_paths` shape them further
before `assert_snapshots` when a test needs to focus on a subset.

### Narrowing the snapshot scope

Filtering with `include_paths` / `exclude_paths` has a sharp edge worth stating
plainly: **a filtered snapshot is blind to anything it was not handed**. If a
test narrows the view to certain files and a new template later writes outside
that set, the comparison passes and the new output goes unseen. The full
`managed_files()` snapshot has no blind spot: adding a template lights up every
fixture's snapshot diff, and reviewing that diff once with
`REPOLISH_UPDATE_SNAPSHOTS=1` is the test doing its job, not a chore. Prefer
paying that review cost over filtering it away.

Reach for a filter only when the full view cannot work, and make determinism the
first attempt: the harness freezes `year=`, `repo_owner=`, and `repo_name=`
precisely so snapshot content never drifts between runs. The cases that justify
filtering:

- a generated file whose content your provider genuinely cannot reproduce
  deterministically (a lockfile with resolved hashes, a file embedding a
  wall-clock timestamp produced by `post_process`), and
- a file that exists only to exercise a side effect (a validator target, scratch
  output of a `post_process` step) whose content carries no information worth
  pinning.

Exclude the single offending path, not the whole category, and keep the
exclusion next to the test with a comment saying why. A comment like
`# lockfile: resolved hashes differ per run` is self-documenting; a bare
`exclude_paths(result.managed_files(), {'generated/'})` in a helper far from the
test is how blind spots accumulate quietly.

### The workflow never changes

The first run is the only setup you ever do:

```bash
REPOLISH_UPDATE_SNAPSHOTS=1 pytest tests/
```

Snapshots are written for you; review the git diff and commit. There is no
"first run without local files" dance: preprocessor directives read the
**fixture files** (the same files the real repo would have), so the test code is
identical on the first and every later run.

The same command is the natural response to **template changes**. As you work on
the provider and edit templates, the generated output, and therefore the
snapshots, changes with it. Re-run the tests with the environment variable set,
then review the diff to see exactly what the change produces across every
fixture project:

```bash
REPOLISH_UPDATE_SNAPSHOTS=1 pytest tests/
```

If a snapshot diff surprises you, that is the test earning its keep: the
template change did something you didn't intend, and you found out before a real
project did.

### Assert the project, not just the render

`ApplyResult` exposes what the pipeline collected:

- `exit_code`: `0` success; `1` validator failure; `2` drift in check mode
- `apply_result`: per-file status: `'written'`, `'unchanged'`, `'deleted'`
- `validation_results`: validator **failures** per destination path (passes
  don't need asserting; the exit code already covers them)
- `insertion_results`: per-file insertion execution summaries
- `render_tree`: the staged render tree, open it to debug a diff

Use `check_only=True` to compare without writing, and `assert_idempotent` for
the test that pays for itself: apply, then check, expecting no drift. A provider
that produces output it can't reproduce on the second pass is the classic
spurious-drift bug, and this catches it:

```python
def test_no_drift(tmp_path: Path) -> None:
    project = stage_project(FIXTURES / 'my-repo', tmp_path / 'project')
    assert_idempotent(MyProvider, project)
```

### Testing validators: bad data belongs in the fixture

Validators generate nothing; they inspect. That is exactly why they pair
naturally with fixtures: the pipeline resolves each validator's target by
preferring the real project file and falling back to the render tree, so a
validator registered for a developer-owned file (`config.toml` the repo already
had, not a template) validates the fixture's copy directly. A fixture with bad
data is just a fixture: check in the broken state you want the validator to
catch, apply, and assert on the records.

Two fixtures, one validator, both sides of the check:

```python
from repolish.providers.models import ValidationStatus


def test_catches_missing_api_key(tmp_path: Path) -> None:
    """The bad fixture fails validation exactly as a real repo would."""
    project = stage_project(FIXTURES / 'config-missing-key', tmp_path / 'project')

    result = apply_provider(MyProvider, project)

    # 1 = validator failure, distinct from 2 (drift) and 0 (clean run)
    assert result.exit_code == 1
    failure = result.validation_results['config.toml']['has-api-key']
    assert failure.status == ValidationStatus.ERROR
    assert 'api_key' in failure.message


def test_accepts_valid_config(tmp_path: Path) -> None:
    """The good fixture passes: nothing lands in validation_results."""
    project = stage_project(FIXTURES / 'config-valid', tmp_path / 'project')

    result = apply_provider(MyProvider, project)

    assert result.exit_code == 0
    assert 'config.toml' not in result.validation_results
```

`validation_results` holds **failures and warnings only**, keyed
`{dest_path: {validator_name: ValidationResult}}`. Passes never appear: a clean
run is already proven by `exit_code == 0` and the empty dict. A validator that
crashes is reported as `ValidationStatus.ERROR` with the same
`"Validator 'name' for 'dest' crashed: ..."` message shape production prints, so
a crash test asserts on exactly what a real run would report. Validators
disabled through `FileValidatorOptions` are skipped entirely, just as in
production.

Warnings are the one nuance: a `ValidationStatus.WARNING` leaves
`exit_code == 0` by default, matching `repolish apply`. Pass
`fail_on_warnings=True` to the harness to test the strict behavior:

```python
result = apply_provider(MyProvider, project, fail_on_warnings=True)
assert result.exit_code == 1
warned = result.validation_results['docs/README.md']['stale-links']
assert warned.status == ValidationStatus.WARNING
```

When a test needs the full picture (passes and disables included, not just
failures), `result.session.validation_reports` maps each destination path to the
JSON report the pipeline wrote under `.repolish/_/validators/`: open it and read
every registered validator's outcome from the run.

### Cross-provider inputs: sending and receiving

Providers talk through inputs: one provider's `provide_inputs()` emits payloads,
and every provider whose `get_inputs_schema()` matches receives them in
`finalize_context()`. The end-to-end harness covers both directions without a
second installed provider.

**Sending**: everything the run emitted is recorded on the result.
`result.emitted_inputs` lists each payload, captured before local routing, so a
provider consuming its own output cannot hide what it sent:

```python
def test_emits_ci_tasks(tmp_path: Path) -> None:
    project = stage_project(FIXTURES / 'my-repo', tmp_path / 'project')

    result = apply_provider(MyProvider, project)

    assert [inp.model_dump() for inp in result.emitted_inputs] == [
        {'ci_tasks': ['lint', 'test']},
    ]
```

**Receiving**: pass `extra_inputs=` to inject payloads into the run. They join
the routing pool before finalization and are delivered by schema match exactly
as a peer provider's outputs would be, so a dependency test needs no real peer:

```python
def test_receives_ci_tasks(tmp_path: Path) -> None:
    project = stage_project(FIXTURES / 'my-repo', tmp_path / 'project')

    result = apply_provider(
        MyProvider,
        project,
        extra_inputs=[CiProviderInputs(ci_tasks=['lint', 'test'])],
    )

    assert result.exit_code == 0
    assert result.apply_result['.github/workflows/ci.yml'] == 'written'
```

Routing matches by schema, not by class identity: a payload from a separate
module is accepted when it validates against the provider's inputs model. Import
the peer provider's inputs class when the peer is installed; define a
structurally identical model in the test when it is not.

For the read pattern (`get_provider_context`) or a full two-provider run,
register the peer through `config=`. Provider entries other than the harness's
alias are kept as written, so both providers load and the pipeline routes inputs
between them for real:

```python
result = apply_provider(
    MyProvider,
    project,
    alias='my-provider',
    config={'providers': {
        'ci': {'provider_root': str(CI_TEMPLATES_ROOT)},
    }},
)
```

`assert_idempotent` accepts `extra_inputs` too and forwards it to both runs, so
a dependency-driven provider gets the same drift guarantee.

`apply_provider` writes the `repolish.yaml` for you; the `config=` mapping
carries everything else you'd put in that file, with the harness's entry for its
own alias always winning over anything you supply there:

```python
result = apply_provider(
    MyProvider,
    project,
    alias='my-provider',
    config={
        'post_process': [f'{sys.executable} -c "..."'],
        'paused_files': ['legacy/old.py'],
    },
)
```

Context values are deterministic by default: `repolish.repo.owner` is
`test-owner`, `repolish.repo.name` is `test-repo`, and nothing is derived from
your cwd or git. Override with `repo_owner` / `repo_name`, freeze
`repolish.year` with `year=` for license headers, and pass `git_init=True` to
`stage_project` when your provider code itself reads git.

Standalone projects are supported; monorepo (root/member) fixtures are not yet
wired through the harness.

### Choosing a tier

- **End-to-end** (`apply_provider`): behavior, output, drift, the tier this page
  recommends; it cannot drift from the pipeline because it _is_ the pipeline.
- **Hook-level** (`ProviderTestBed`): fast unit tests for context, mappings,
  inputs, and validators in isolation. See below.
- **`run_snapshot_case`**: the earlier snapshot pattern, retained as-is. It may
  be deprecated in a future release as the end-to-end tier covers its use cases.

---

## Snapshot Tests with `run_snapshot_case`

For most snapshot tests, use `run_snapshot_case()` with `SnapshotRunOptions`.
This captures the common flow in a single call:

```python
from pathlib import Path

from repolish.testing import SnapshotRunOptions, run_snapshot_case, include_paths
from my_provider.repolish.provider import MyProvider
from my_provider.repolish.models import MyProviderInputs

SNAPSHOT_DIR = Path(__file__).parent / 'snapshots' / 'my_provider'


def test_standalone_snapshot() -> None:
    opts = SnapshotRunOptions[MyProviderInputs](
        mode='standalone',
        received_inputs=[],
        preprocess=True,
        local_files_dir=SNAPSHOT_DIR,
    )

    ctx, rendered = run_snapshot_case(
        MyProvider,
        options=opts,
        snapshot_dir=SNAPSHOT_DIR,
    )

    # Extra assertions beyond snapshot comparison
    assert 'expected_value' in rendered['config.toml']


def test_root_mode_with_filter() -> None:
    """Filter rendered output to only snapshot relevant files."""
    opts = SnapshotRunOptions[MyProviderInputs](
        mode='root',
        received_inputs=[MyProviderInputs(feature='enabled')],
        local_files_dir=SNAPSHOT_DIR,
    )

    ctx, rendered = run_snapshot_case(
        MyProvider,
        options=opts,
        snapshot_dir=SNAPSHOT_DIR / 'root',
        filter_rendered=lambda r: include_paths(
            r,
            exact={'README.md', 'config.toml'},
            prefixes=('tasks/',),
            exclude_prefixes=('tasks/sessions/',),
        ),
    )
```

### SnapshotRunOptions parameters

| Parameter         | Type                                      | Default        | Description                                                                                                      |
| ----------------- | ----------------------------------------- | -------------- | ---------------------------------------------------------------------------------------------------------------- |
| `mode`            | `'standalone'` \| `'root'` \| `'member'`  | `'standalone'` | Workspace mode for context and mode-handler dispatch.                                                            |
| `received_inputs` | `list[BaseInputs]`                        | `[]`           | Inputs from other providers to merge in `finalize()`.                                                            |
| `all_providers`   | `list[ProviderEntry]` or `None`           | `None`         | Provider entries visible during input emission / finalization. Defaults to single-entry list with this provider. |
| `provider_index`  | `int`                                     | `0`            | Position in the load order.                                                                                      |
| `preprocess`      | `bool`                                    | `True`         | Run the full preprocessing pipeline after Jinja2 rendering.                                                      |
| `local_files_dir` | `Path` or `None`                          | `None`         | Directory of existing local files for preprocessor directives to read from.                                      |
| `extra_context`   | `dict[str, object]` or `None`             | `None`         | Additional variables merged on top of provider context during rendering.                                         |
| `mutate_context`  | `Callable[[BaseContext], None]` or `None` | `None`         | Optional callback to mutate context after `finalize()` for one-off customizations.                               |

### Filter helpers

Use `include_paths()` and `exclude_paths()` to filter rendered output before
snapshot comparison. This is useful for mode-specific tests or excluding
generated paths.

```python
from repolish.testing import include_paths, exclude_paths

# Include only specific files and paths under 'tasks/', excluding sessions
filtered = include_paths(
    rendered,
    exact={'README.md', 'config.toml'},
    prefixes=('tasks/',),
    exclude_prefixes=('tasks/sessions/',),
    include_regex=(r'.*\.jinja$',),      # Also include any .jinja files
    exclude_regex=(r'.*\.tmp$',),        # Exclude any .tmp files
)

# Or exclude specific paths from the full output
filtered = exclude_paths(
    rendered,
    prefixes=('generated/', '.git/'),
    regex=(r'.*\.cache$',),
)
```

### Snapshot workflow: first run vs subsequent runs

**First run** (snapshots don't exist yet):

```python
def test_standalone_snapshot() -> None:
    opts = SnapshotRunOptions[MyProviderInputs](
        preprocess=True,
        # No local_files_dir on first run
    )

    ctx, rendered = run_snapshot_case(
        MyProvider,
        options=opts,
        snapshot_dir=SNAPSHOT_DIR,  # Will fail with rendered content shown
    )
```

The test fails with missing snapshot errors: the assertion prints the rendered
content so you can copy it into `SNAPSHOT_DIR`.

**Subsequent runs** (feed snapshot content back as local files):

```python
def test_standalone_snapshot() -> None:
    opts = SnapshotRunOptions[MyProviderInputs](
        preprocess=True,
        local_files_dir=SNAPSHOT_DIR,  # Read from snapshots for regex/keep
    )

    ctx, rendered = run_snapshot_case(
        MyProvider,
        options=opts,
        snapshot_dir=SNAPSHOT_DIR,
    )
```

With `local_files_dir` set, preprocessor directives can extract values from the
existing snapshot files, exactly as `repolish apply` reads from the real repo.

### Why this pattern?

- Removes boilerplate: no repeated `ProviderTestBed` construction, `finalize()`,
  `render_all()` calls
- Explicit defaults: `SnapshotRunOptions` makes all parameters visible
- Flexible filtering: `include_paths()` / `exclude_paths()` for mode-specific
  snapshot subsets
- Full compatibility: advanced tests can still use `ProviderTestBed` directly

---

## Testing Cross-Provider Dependencies

Providers can communicate in two ways:

1. **Push pattern** (via `provide_inputs()` / `finalize_context()`): One
   provider emits typed inputs that another receives. Test this by passing
   `received_inputs` to `SnapshotRunOptions`.

2. **Read pattern** (via `get_provider_context()`): A provider reads another
   provider's context directly from `opt.all_providers`. Test this by
   constructing mock provider entries with `mock_provider_entry()`.

### Testing the read pattern

When your provider reads another provider's context (e.g., CI-checks reading
Poe's tasks), use `mock_provider_entry()` to create a fake peer provider:

```python
from repolish.testing import (
    SnapshotRunOptions,
    run_snapshot_case,
    mock_provider_entry,
)


def test_ci_checks_with_poe_context() -> None:
    """Test CI-checks provider reading Poe provider's context."""
    # Mock the Poe provider with pre-populated context
    poe_entry = mock_provider_entry(
        PoeProvider,
        context=PoeCtx(ci_tasks=['lint', 'test', 'typecheck']),
        alias='poe',
    )

    opts = SnapshotRunOptions(
        all_providers=[poe_entry],
    )

    ctx, rendered = run_snapshot_case(
        CIChecksProvider,
        options=opts,
        snapshot_dir=SNAPSHOT_DIR,
    )

    # CI-checks should have generated workflows for each Poe task
    assert 'lint' in rendered['ci-workflows.toml']
    assert 'test' in rendered['ci-workflows.toml']
```

### Testing the push pattern

When your provider receives inputs from another provider, pass them via
`received_inputs`:

```python
from other_provider.repolish.models import OtherProviderInputs


def test_workspace_with_python_inputs() -> None:
    """Test workspace provider receiving inputs from Python provider."""
    opts = SnapshotRunOptions[OtherProviderInputs](
        received_inputs=[
            OtherProviderInputs(poe_tasks_block='check-ruff.help = "..."'),
        ],
        local_files_dir=SNAPSHOT_DIR,
    )

    ctx, rendered = run_snapshot_case(
        WorkspaceProvider,
        options=opts,
        snapshot_dir=SNAPSHOT_DIR,
    )

    # Workspace should have merged the Python provider's tasks
    assert 'check-ruff' in rendered['poe_tasks.toml']
```

### Full example: CI-checks reading from Poe

```python
from repolish import BaseContext, FinalizeContextOptions, Provider, get_provider_context
from repolish.testing import SnapshotRunOptions, run_snapshot_case, mock_provider_entry


class PoeCtx(BaseContext):
    ci_tasks: list[str] = ['lint']


class PoeProvider(Provider[PoeCtx, BaseInputs]):
    def create_context(self) -> PoeCtx:
        return PoeCtx()


class CIChecksCtx(BaseContext):
    workflow_tasks: list[str] = []
    project: str = 'my-project'


class CIChecksProvider(Provider[CIChecksCtx, BaseInputs]):
    def finalize_context(
        self,
        opt: FinalizeContextOptions[CIChecksCtx, BaseInputs],
    ) -> CIChecksCtx:
        # Read Poe's context directly
        poe = get_provider_context(PoeProvider, opt.all_providers)
        if poe is not None:
            opt.own_context.workflow_tasks = poe.ci_tasks
        return opt.own_context

    def create_file_mappings(self, context: CIChecksCtx) -> dict:
        return {'ci-workflows.toml': 'ci-workflows.toml.jinja'}


def test_ci_checks_reads_poe_tasks() -> None:
    SNAPSHOT_DIR = Path(__file__).parent / 'snapshots'

    # Mock Poe provider with specific tasks
    poe_entry = mock_provider_entry(
        PoeProvider,
        context=PoeCtx(ci_tasks=['lint', 'test', 'typecheck']),
    )

    opts = SnapshotRunOptions(
        all_providers=[poe_entry],
    )

    ctx, rendered = run_snapshot_case(
        CIChecksProvider,
        options=opts,
        snapshot_dir=SNAPSHOT_DIR,
    )

    assert ctx.workflow_tasks == ['lint', 'test', 'typecheck']
```

---

## Deterministic Snapshots for Dynamic Values

Snapshot tests should be deterministic. If provider output includes dynamic
values (current year/month, timestamps, random IDs, or environment-derived
values), freeze or patch them in tests.

Preferred pattern: use `mocker: MockerFixture` and `mock.patch` to patch the
function or module that produces the dynamic value:

```python
from pytest_mock import MockerFixture

from repolish.testing import SnapshotRunOptions, run_snapshot_case


def test_snapshot_stable_year(mocker: MockerFixture) -> None:
    """Freeze the year to prevent snapshot drift."""
    mocker.patch('my_provider.repolish.provider.current_year', return_value=2026)

    opts = SnapshotRunOptions()
    ctx, rendered = run_snapshot_case(
        MyProvider,
        options=opts,
        snapshot_dir=SNAPSHOT_DIR,
    )
    # Snapshots remain stable over time
```

Common values to freeze:

| Value           | Patch target                                                   | Example                                                                   |
| --------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Current year    | `repolish.provider.current_year` or your provider's equivalent | `mocker.patch('my_provider.provider.current_year', return_value=2026)`    |
| Current month   | Similar pattern                                                | `mocker.patch('my_provider.provider.current_month', return_value='July')` |
| Timestamps      | `datetime.datetime.now`                                        | `mocker.patch('datetime.datetime.now', return_value=fixed_dt)`            |
| Random IDs      | `uuid.uuid4` or `random`                                       | `mocker.patch('uuid.uuid4', return_value=fixed_uuid)`                     |
| Version strings | Your provider's version source                                 | `mocker.patch('my_provider.__version__', return_value='1.0.0')`           |

---

## Advanced: Direct ProviderTestBed Usage

For tests that need fine-grained control over individual lifecycle hooks, use
`ProviderTestBed` directly.

---

## ProviderTestBed

`ProviderTestBed` is a dataclass that wraps a provider instance, injects a
synthetic context, and exposes methods mirroring every lifecycle hook.

### Quick start

```python
from repolish.testing import ProviderTestBed
from my_provider.repolish.provider import MyProvider

bed = ProviderTestBed(MyProvider)
assert bed.resolved_context.repolish.workspace.mode == 'standalone'
```

When no context is supplied the provider's own `create_context()` is called.
Pass an explicit context to override:

```python
from my_provider.repolish.models import MyProviderContext

bed = ProviderTestBed(
    MyProvider,
    context=MyProviderContext(flag=True),
)
assert bed.resolved_context.flag is True
```

### Constructor parameters

| Parameter         | Type                                     | Default           | Description                                                                                                                                                                                  |
| ----------------- | ---------------------------------------- | ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `provider_class`  | `type[Provider]`                         | required          | The concrete `Provider` subclass to test.                                                                                                                                                    |
| `context`         | context model or `None`                  | `None`            | If `None`, calls `create_context()` on the provider.                                                                                                                                         |
| `mode`            | `'standalone'` \| `'root'` \| `'member'` | `'standalone'`    | Controls mode-handler dispatch and `repolish.workspace.mode`.                                                                                                                                |
| `templates_root`  | `Path` or `None`                         | `None`            | Explicit path to `resources/templates`. Auto-detected when omitted.                                                                                                                          |
| `alias`           | `str`                                    | `'test-provider'` | Provider alias injected into instance metadata.                                                                                                                                              |
| `version`         | `str`                                    | `'0.1.0'`         | Provider version injected into instance metadata.                                                                                                                                            |
| `preprocess`      | `bool`                                   | `False`           | Run the full preprocessing pipeline after Jinja2 rendering. Strips preprocessor directive lines and applies anchor replacements, matching `repolish apply` production output.                |
| `local_files_dir` | `Path` or `None`                         | `None`            | Directory of existing local files passed as `local_content` to the preprocessor. Only used when `preprocess=True`. See [Snapshot workflow](#snapshot-tests-with-full-pipeline-output) below. |

### Lifecycle hook methods

Each method calls the corresponding provider hook through the same dispatch path
that `repolish apply` uses, including mode-handler routing:

```python
bed.file_mappings()         # -> dict[str, str | TemplateMapping | None]
bed.anchors()               # -> dict[str, str]
bed.symlinks()              # -> list[Symlink]
bed.promote_file_mappings() # -> dict[str, str | TemplateMapping | None]
bed.validators()            # -> dict[str, dict[str, FileValidatorEntry]]
bed.insertions()            # -> FileInsertionContribution
bed.insertion_registry()    # -> InsertionRegistry
bed.copies()                # -> list[ResourceCopy]
bed.provide_inputs()        # -> Sequence[BaseInputs]
bed.finalize(received_inputs=[])  # -> context
```

`provide_inputs()` and `finalize()` accept optional `all_providers` and
`provider_index` keyword arguments. When omitted they default to a single-entry
list containing the test provider itself.

`validators()`, `insertions()`, and `insertion_registry()` route through the
same mode-handler dispatch as `repolish apply`. `copies()` and `symlinks()` are
no-argument hooks and call the provider instance directly.

### Running validators

`run_validators()` executes the registry returned by `create_file_validators()`
against real files, so a provider can test its validators the way the pipeline
runs them:

```python
bed = ProviderTestBed(MyProvider)

results = bed.run_validators({'config.toml': 'generated by repolish\n'})
header = results['config.toml']['lint']
assert header.status == ValidationStatus.PASS
```

- `files` maps destination paths to file content. It defaults to the output of
  `render_all()`, so `bed.run_validators()` validates the provider's rendered
  output in one call.
- The files are materialized under `base_dir` when given, otherwise a throwaway
  temporary directory that is removed after the run. Validators receive a real
  path to read from, just like in `repolish apply`.
- The return value is `{dest_path: {validator_name: ValidationResult}}` with one
  entry per **enabled** validator that ran, passes included. Validators disabled
  through `FileValidatorOptions` (either `enabled=False` or the per-name
  `validators` map) are skipped.
- A validator that raises is reported as `ValidationStatus.ERROR` with the same
  `"Validator 'name' for 'dest' crashed: ..."` message shape the apply pipeline
  produces, so a crash test asserts on exactly what production would report.

### Template rendering

#### `render(template_name, *, extra_context=None)`

Renders a single template from `resources/templates/repolish/` using the
provider's context (flattened through `ctx_to_dict`, matching production).

```python
bed = ProviderTestBed(MyProvider)
output = bed.render('mise.toml.jinja')
assert '[tools]' in output
```

#### `render_all(*, extra_context=None)`

Renders every file returned by `create_file_mappings()` plus auto-discovered
templates, returning a `{dest_path: rendered_content}` dict:

```python
rendered = bed.render_all()
assert '.github/workflows/ci.yml' in rendered
assert 'my-project' in rendered['README.md']
```

Auto-discovery mirrors production behavior: files in `templates/repolish/`
without the `_repolish.` prefix are included automatically, while `_repolish.`
prefixed files appear only when explicitly mapped.

`render_all()` also respects `TemplateMapping.extra_context`. When a mapping
entry carries per-file extra context, it is merged on top of the provider
context for that destination only, exactly as `repolish apply` does. This means
a single template can fan out to multiple files with different content:

```python
class SessionCtx(BaseModel):
    session_name: str

class MyProvider(Provider[Ctx, BaseInputs]):
    def create_file_mappings(self, context: Ctx):
        return {
            f'poe-tasks/{s.session_name}.toml': TemplateMapping(
                '_repolish.task.toml.jinja',
                extra_context=SessionCtx(session_name=s.session_name),
            )
            for s in context.session_tasks
        }

bed = ProviderTestBed(MyProvider)
rendered = bed.render_all()
# Each destination gets its own session_name baked in
assert 'session_name = lint' in rendered['poe-tasks/lint.toml']
```

#### Snapshot tests with full pipeline output

By default the testbed only performs Jinja2 rendering, keeping tests fast.
Enable `preprocess=True` to also run the preprocessing pipeline
(`repolish-regex`, `repolish-keep-*`, anchor replacements, etc.), producing
output that matches `repolish apply` exactly.

See
[Snapshot workflow: first run vs subsequent runs](#snapshot-workflow-first-run-vs-subsequent-runs)
above for the recommended pattern using `run_snapshot_case()`. For direct
`ProviderTestBed` usage:

```python
SNAPSHOT_DIR = Path(__file__).parent / 'snapshots' / 'my_provider'

def test_render_all_pipeline_output() -> None:
    # First run: no local_files_dir, snapshots don't exist yet
    bed = ProviderTestBed(MyProvider, preprocess=True)
    rendered = bed.render_all()
    assert_snapshots(rendered, SNAPSHOT_DIR)

def test_render_all_pipeline_output_with_local_files() -> None:
    # Subsequent runs: feed snapshots back as local content
    bed = ProviderTestBed(
        MyProvider,
        preprocess=True,
        local_files_dir=SNAPSHOT_DIR,
    )
    rendered = bed.render_all()
    assert_snapshots(rendered, SNAPSHOT_DIR)
```

---

## make_context

Factory for a synthetic `RepolishContext` with sensible defaults. Useful when
building context objects for tests without constructing the full object graph:

```python
from repolish.testing import make_context

ctx = make_context(mode='root', alias='my-provider', version='2.0.0')
assert ctx.workspace.mode == 'root'
assert ctx.provider.alias == 'my-provider'
```

| Parameter    | Default           | Description                             |
| ------------ | ----------------- | --------------------------------------- |
| `mode`       | `'standalone'`    | `'standalone'`, `'root'`, or `'member'` |
| `alias`      | `'test-provider'` | Provider alias                          |
| `version`    | `'0.1.0'`         | Provider version                        |
| `repo_owner` | `'test-owner'`    | GitHub repo owner                       |
| `repo_name`  | `'test-repo'`     | GitHub repo name                        |

---

## assert_snapshots

Compares rendered output against golden files on disk. Produces a unified diff
on mismatch and reports missing snapshots with the rendered content so you can
copy it into place:

```python
from repolish.testing import ProviderTestBed, assert_snapshots

bed = ProviderTestBed(MyProvider)
rendered = bed.render_all()
assert_snapshots(rendered, 'tests/snapshots/my_provider')
```

### Workflow

1. Run `render_all()` to get the rendered output dict.
2. Create a `tests/snapshots/` directory with expected files matching each key.
3. Call `assert_snapshots(rendered, snapshot_dir)`.
4. On first run (empty snapshot dir), the assertion fails with the rendered
   content printed; copy it into the snapshot directory.
5. On subsequent runs, any drift produces a readable unified diff.

```
AssertionError: 1 snapshot(s) failed:
  Failed files:
    - README.md

--- snapshot/README.md
+++ rendered/README.md
@@ -1,3 +1,3 @@
-# old-project
+# new-project
```

### Snapshot update mode

To update snapshots automatically instead of failing, use the `update` parameter
or set the `REPOLISH_UPDATE_SNAPSHOTS=1` environment variable:

```python
# Option 1: Pass update=True to assert_snapshots
assert_snapshots(rendered, 'tests/snapshots/my_provider', update=True)

# Option 2: Use environment variable
# Run: REPOLISH_UPDATE_SNAPSHOTS=1 pytest tests/
```

When update mode is enabled:

- A warning is printed to stderr reminding you to review git changes
- All rendered files are written to the snapshot directory
- No assertion errors are raised

**Important:** Always review the git diff before committing updated snapshots!

---

## Testing mode handlers

`ProviderTestBed` routes calls through the same `call_provider_method` dispatch
that production uses. Set the `mode` parameter to exercise specific handlers:

```python
bed_root = ProviderTestBed(MyProvider, mode='root')
root_mappings = bed_root.file_mappings()

bed_member = ProviderTestBed(MyProvider, mode='member')
member_mappings = bed_member.file_mappings()

assert 'root-only.md' in root_mappings
assert 'member-only.md' in member_mappings
```

---

## Testing cross-provider inputs

Exercise `provide_inputs()` and `finalize()` to verify input exchange without
running the full pipeline:

```python
from my_provider.repolish.models import MyProviderInputs

bed = ProviderTestBed(MyProvider)

# Check what inputs this provider emits
inputs = bed.provide_inputs()
assert len(inputs) == 1

# Simulate receiving inputs from another provider
result = bed.finalize(received_inputs=[MyProviderInputs(flag=True)])
assert result.some_field == 'derived-from-input'
```

---

## Full Examples

### Canonical pattern (recommended)

Use `run_snapshot_case()` for most snapshot tests:

```python
from pathlib import Path

from pytest_mock import MockerFixture

from my_provider.repolish.models import MyProviderContext, MyProviderInputs
from my_provider.repolish.provider import MyProvider
from repolish.testing import SnapshotRunOptions, run_snapshot_case, include_paths

SNAPSHOT_DIR = Path(__file__).parent / 'snapshots' / 'my_provider'


def test_standalone_default() -> None:
    """Basic snapshot test with defaults."""
    opts = SnapshotRunOptions[MyProviderInputs](
        preprocess=True,
        local_files_dir=SNAPSHOT_DIR,
    )

    ctx, rendered = run_snapshot_case(
        MyProvider,
        options=opts,
        snapshot_dir=SNAPSHOT_DIR,
    )


def test_root_mode_filtered(mocker: MockerFixture) -> None:
    """Root mode with filtered output and frozen dynamic values."""
    # Freeze dynamic values for stable snapshots
    mocker.patch('my_provider.provider.current_year', return_value=2026)

    opts = SnapshotRunOptions[MyProviderInputs](
        mode='root',
        received_inputs=[MyProviderInputs(feature='enabled')],
        local_files_dir=SNAPSHOT_DIR,
    )

    ctx, rendered = run_snapshot_case(
        MyProvider,
        options=opts,
        snapshot_dir=SNAPSHOT_DIR / 'root',
        filter_rendered=lambda r: include_paths(
            r,
            exact={'README.md', 'config.toml'},
            prefixes=('tasks/',),
            exclude_prefixes=('tasks/sessions/',),
        ),
    )

    # Extra assertions beyond snapshot comparison
    assert 'expected_value' in rendered['config.toml']


def test_mutate_context() -> None:
    """Use mutate_context for one-off context customizations."""
    def apply_overrides(ctx: MyProviderContext) -> None:
        ctx.project_name = 'overridden-project'
        ctx.feature_flag = True

    opts = SnapshotRunOptions[MyProviderInputs](
        mutate_context=apply_overrides,
    )

    ctx, rendered = run_snapshot_case(
        MyProvider,
        options=opts,
        snapshot_dir=SNAPSHOT_DIR / 'overridden',
    )
```

### Advanced pattern (fine-grained control)

Use `ProviderTestBed` directly when you need to test individual hooks:

```python
from pathlib import Path

from my_provider.repolish.models import MyProviderContext, MyProviderInputs
from my_provider.repolish.provider import MyProvider
from repolish.testing import ProviderTestBed, assert_snapshots, make_context

SNAPSHOT_DIR = Path(__file__).parent / 'snapshots' / 'my_provider'


def test_default_context() -> None:
    bed = ProviderTestBed(MyProvider)
    ctx = bed.resolved_context
    assert isinstance(ctx, MyProviderContext)
    assert ctx.project_name == 'my-project'


def test_file_mappings() -> None:
    bed = ProviderTestBed(MyProvider)
    fm = bed.file_mappings()
    assert 'README.md' in fm
    assert fm.get('SETUP.md') is not None


def test_anchors() -> None:
    bed = ProviderTestBed(MyProvider)
    anchors = bed.anchors()
    assert 'project-name' in anchors


def test_mode_handlers() -> None:
    """Test different mode handler behavior."""
    bed_root = ProviderTestBed(MyProvider, mode='root')
    root_mappings = bed_root.file_mappings()

    bed_member = ProviderTestBed(MyProvider, mode='member')
    member_mappings = bed_member.file_mappings()

    assert 'root-only.md' in root_mappings
    assert 'member-only.md' in member_mappings


def test_cross_provider_inputs() -> None:
    """Test input exchange between providers."""
    bed = ProviderTestBed(MyProvider)

    # Check what inputs this provider emits
    inputs = bed.provide_inputs()
    assert len(inputs) == 1

    # Simulate receiving inputs from another provider
    result = bed.finalize(received_inputs=[MyProviderInputs(flag=True)])
    assert result.some_field == 'derived-from-input'


def test_render_all_matches_snapshots() -> None:
    bed = ProviderTestBed(
        MyProvider,
        preprocess=True,
        local_files_dir=SNAPSHOT_DIR,
    )
    rendered = bed.render_all()
    assert_snapshots(rendered, SNAPSHOT_DIR)


def test_custom_context_changes_output() -> None:
    bed = ProviderTestBed(
        MyProvider,
        context=MyProviderContext(project_name='custom'),
    )
    rendered = bed.render_all()
    assert 'custom' in rendered['README.md']


def test_template_mapping_extra_context() -> None:
    """Test fanning out a single template to multiple destinations."""
    from pydantic import BaseModel
    from repolish import TemplateMapping

    class SessionCtx(BaseModel):
        session_name: str

    class FanOutProvider(MyProvider):
        def create_file_mappings(self, context: MyProviderContext):
            return {
                f'tasks/{name}.toml': TemplateMapping(
                    '_repolish.task.toml.jinja',
                    extra_context=SessionCtx(session_name=name),
                )
                for name in ['lint', 'test', 'build']
            }

    bed = ProviderTestBed(FanOutProvider)
    rendered = bed.render_all()

    assert 'session_name = lint' in rendered['tasks/lint.toml']
    assert 'session_name = test' in rendered['tasks/test.toml']
    assert 'session_name = build' in rendered['tasks/build.toml']
```
