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

## Quick Start: Snapshot Tests (Recommended Pattern)

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

**First run** — snapshots don't exist yet:

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

The test fails with missing snapshot errors — the assertion prints the rendered
content so you can copy it into `SNAPSHOT_DIR`.

**Subsequent runs** — feed snapshot content back as local files:

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

1. **Push pattern** — via `provide_inputs()` / `finalize_context()`: One
   provider emits typed inputs that another receives. Test this by passing
   `received_inputs` to `SnapshotRunOptions`.

2. **Read pattern** — via `get_provider_context()`: A provider reads another
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
bed.provide_inputs()        # -> Sequence[BaseInputs]
bed.finalize(received_inputs=[])  # -> context
```

`provide_inputs()` and `finalize()` accept optional `all_providers` and
`provider_index` keyword arguments. When omitted they default to a single-entry
list containing the test provider itself.

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
context for that destination only — exactly as `repolish apply` does. This means
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
   content printed — copy it into the snapshot directory.
5. On subsequent runs, any drift produces a readable unified diff.

```
AssertionError: 1 snapshot(s) failed:

--- snapshot/README.md
+++ rendered/README.md
@@ -1,3 +1,3 @@
-# old-project
+# new-project
```

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
