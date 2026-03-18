# Monorepo Support — Detailed Action Plan

This document describes the implementation plan for monorepo support in
repolish, targeting v1. It is structured as a sequence of phases that Sonnet
should follow in order. Each phase builds on the previous one.

The design document lives in `tests/mono-repo-support.tmp.md`. This action
plan supersedes the API sketch in that document — specifically, the
`provide_inputs_to_root` / `aggregate_member_inputs` methods are **not**
being implemented. The member-to-root channel uses a simpler approach
described below.

> **Testing strategy**: all new behaviour is tested via integration tests.
> We already have the machinery in `tests/integration/conftest.py`
> (`FixtureRepo`, `InstalledProviders`, `run_repolish`) and
> `provider-examples/` to create providers and fixtures that simulate
> real multi-provider interactions. Unit tests for individual models
> (frozen Pydantic classes) are acceptable but the emphasis is on
> integration tests that exercise provider orchestration end-to-end.

---

## Terminology

| Term | Meaning |
|------|---------|
| **root** | The top-level directory containing `pyproject.toml` with `[tool.uv.workspace]`. |
| **member** | A subdirectory listed in `[tool.uv.workspace] members` that contains its own `repolish.yaml`. |
| **standalone** | A repo that is not a monorepo (today's default mode). |
| **dry pass** | Running the provider pipeline (context creation → input exchange → finalization) without writing any files (no `create_file_mappings`, no staging, no rendering). |
| **full pass** | The complete repolish pipeline: provider pipeline + staging + preprocessing + rendering + apply. This is what `apply.command()` does today. |

---

## Architecture Overview

### Execution flow for `repolish apply` in a monorepo

```
1. Detect monorepo (read pyproject.toml for [tool.uv.workspace])
2. Discover members (glob-expand workspace members, filter for repolish.yaml)
3. For each linkable member:
     Run a DRY provider pipeline (create_context → provide_inputs →
     finalize_context). No file writes. Collect:
     - ProviderEntry objects (alias, context, input_type) per member provider
     - Raw provide_inputs outputs (list[BaseInputs]) per member provider
4. Build MonorepoContext with mode="root"
5. Run the FULL root pass (inject MonorepoContext into GlobalContext)
     During input gathering, member providers' emitted inputs are
     injected into the routing pool alongside root providers' inputs.
     all_providers is the combined list: root entries + member entries.
     Root providers' finalize_context sees received_inputs from both
     root peers and member providers, routed via schema matching.
6. For each linkable member:
     Build MonorepoContext with mode="package" for that member
     Run a FULL pass in the member's directory (inject MonorepoContext)
     Each member pass is fully isolated: own repolish.yaml, own providers,
     own .repolish/ directory.
```

### Standalone mode

When not in a monorepo, the flow is identical to today. `MonorepoContext`
is present on `GlobalContext` with `mode="standalone"` and `members=[]`.
No behaviour changes. All existing tests pass unmodified.

### The member-to-root data channel

Instead of adding two new methods to `Provider` (`provide_inputs_to_root`,
`aggregate_member_inputs`), we reuse the **existing `provide_inputs` /
`finalize_context` protocol** — the same typed, schema-based communication
channel that providers already use to talk to each other.

The key insight: a provider's input schema (`get_inputs_schema`) already
defines the shape of data it can consume. If a member python provider
emits `WorkspaceProviderInputs` during its dry pass, and the root
workspace provider declares `get_inputs_schema() -> WorkspaceProviderInputs`,
the existing schema-based routing can deliver those inputs automatically.
We don't need a new channel — we just need to widen the routing to cross
the member/root boundary.

**What the dry pass collects (step 3):**

For each member, we run the standard provider pipeline up to (but not
including) `create_file_mappings`. This is the same code path that runs
today. We collect two things:

1. **`ProviderEntry` objects** — one per member provider. These carry
   `alias`, `context`, `input_type`, and `inst_type`. They are the same
   metadata objects that `all_providers` already contains during a normal
   pass.
2. **Emitted inputs** — the raw `list[BaseInputs]` that each member
   provider returned from `provide_inputs()`. During a normal pass these
   would be routed to peers within the same member; here we also carry
   them forward for the root pass.

**How the root pass consumes them (step 5):**

During the root pass, the orchestrator extends the pipeline in two ways:

- **`all_providers`** is the combined list: root provider entries + all
  member provider entries. This means any root provider's `provide_inputs`
  and `finalize_context` can inspect member providers' aliases, input
  types, and contexts — the same way providers inspect their peers today.
- **Input routing** includes the member-emitted inputs alongside root
  providers' own `provide_inputs` outputs. The standard `_schema_matches`
  routing delivers each input to every root provider whose input schema
  accepts it.

The result: a root provider's `finalize_context` receives `received_inputs`
that contains inputs from both root peers **and** member providers. The
provider doesn't need to know whether an input came from a root peer or a
member — the schema is the contract.

**Why inputs, not contexts:**

A provider knows the shape of its own input schema — that's what
`get_inputs_schema` declares. But it may not know the shape of a foreign
provider's context. Exposing raw `BaseContext` objects from members would
force providers to guess at field names with `getattr(ctx, 'greeting', '?')`.
Inputs are the designed, typed communication channel. They're what
providers already use. Extending the routing to include member inputs
means zero new concepts for provider authors.

**Example — root workspace provider absorbing member data:**

```python
class WorkspaceProvider(Provider[WorkspaceCtx, WorkspaceProviderInputs]):

    def finalize_context(self, own_context, received_inputs, all_providers, provider_index):
        # received_inputs includes WorkspaceProviderInputs from:
        #   - root peers (if any emit them)
        #   - member providers (carried from dry passes)
        for inp in received_inputs:
            own_context.all_task_files.extend(inp.poe_task_files)
            own_context.mono_task_names.extend(inp.mono_task_names)
        return own_context

    def create_file_mappings(self, context):
        mode = context.repolish.monorepo.mode
        if mode == "root":
            # context already has aggregated data from finalize_context
            return self._root_mappings(context)
        if mode == "package":
            return self._package_mappings(context)
        return self._standalone_mappings(context)
```

**Example — member python provider emitting inputs for the root:**

```python
class PythonProvider(Provider[PythonCtx, PythonProviderInputs]):

    def provide_inputs(self, own_context, all_providers, provider_index):
        # This runs during the member's dry pass AND during the member's
        # full pass. The same inputs are emitted either way.
        # During the dry pass, these are collected and carried to the root.
        # During the full pass, they're routed to peers within the member.
        return [WorkspaceProviderInputs(
            poe_task_files=[f'.repolish/{self.project_name}/poe/tasks.yaml'],
            mono_task_names=['check-coverage'],
        )]
```

No new Provider API. No dual input systems. The only change is that the
root pass's input routing pool includes inputs from member dry passes.

---

## Phase 1: Models

### 1.1 — Add `MemberInfo` model

**File**: `repolish/loader/models/context.py`

Add a frozen Pydantic model:

```python
class MemberInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: Path                              # repo-relative path to the member
    name: str                               # package name from pyproject.toml [project].name
    provider_aliases: frozenset[str]        # provider keys from the member's repolish.yaml
```

Notes:
- `provider_aliases` is a `frozenset[str]` not a method. Templates can use
  `{% if 'python' in member.provider_aliases %}` which is simpler and more
  Pythonic than `member.has_provider('python')`.
- `path` is repo-relative (e.g. `packages/core`), not absolute.
- `name` comes from parsing the member's `pyproject.toml` `[project].name`.

### 1.2 — Add `MonorepoContext` model

**File**: `repolish/loader/models/context.py`

```python
class MonorepoContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: Literal["root", "package", "standalone"] = "standalone"
    root_dir: Path = Field(default_factory=lambda: Path.cwd())
    package_dir: Path | None = None
    members: list[MemberInfo] = Field(default_factory=list)
```

Key decisions:
- Frozen. Providers cannot mutate this.
- `members` is always populated in both `root` and `package` modes. Empty
  in `standalone`.
- There is **no `member_contexts` field**. Member data reaches root
  providers through the input routing mechanism described in "The
  member-to-root data channel" section. The orchestrator injects member
  `ProviderEntry` objects into `all_providers` and member-emitted inputs
  into the root pass's routing pool — this is pipeline-level wiring, not
  something exposed on the context model.
- Providers that need to enumerate members or check which providers a
  member uses should read the `members` list and its `provider_aliases`
  field.

### 1.3 — Add `monorepo` field to `GlobalContext`

**File**: `repolish/loader/models/context.py`

Currently `GlobalContext` has `repo: GithubRepo` and `year: int`. Add:

```python
class GlobalContext(BaseModel):
    repo: GithubRepo = Field(default_factory=GithubRepo)
    year: int = Field(default_factory=lambda: ...)
    monorepo: MonorepoContext = Field(default_factory=MonorepoContext)
```

This means every provider's context has `repolish.monorepo` available.
Templates access it as `{{ repolish.monorepo.mode }}`. Provider code accesses
it as `own_context.repolish.monorepo`. The default is standalone mode so
nothing changes for non-monorepo users.

### 1.4 — Add optional `monorepo` section to `RepolishConfigFile`

**File**: `repolish/config/models/project.py`

Add a new optional model:

```python
class MonorepoConfig(BaseModel):
    members: list[str] | None = None  # explicit member paths override uv detection
```

Add to `RepolishConfigFile`:

```python
class RepolishConfigFile(BaseModel):
    ...
    monorepo: MonorepoConfig | None = Field(
        default=None,
        description='Optional monorepo configuration. When present, enables '
                    'monorepo mode. members overrides auto-detection from '
                    '[tool.uv.workspace].',
    )
```

When `monorepo` is present with explicit `members`, skip uv detection.
When `monorepo` is `None`, fall back to structural detection from
`pyproject.toml`.

---

## Phase 2: Monorepo Detection & Member Discovery

### 2.1 — Create `repolish/config/monorepo.py`

This is a new module. Three public functions:

**`detect_monorepo(config_dir: Path) -> MonorepoContext | None`**

1. Look for `pyproject.toml` in `config_dir`.
2. Parse it with `tomllib`. Look for `[tool.uv.workspace]` → `members` key.
3. If not found, return `None` (standalone).
4. If found, glob-expand the member patterns relative to `config_dir`.
5. For each expanded path, check if `repolish.yaml` exists. If yes,
   it's a linkable member.
6. For each linkable member:
   - Parse its `pyproject.toml` to get the `[project].name`.
   - Parse its `repolish.yaml` to get the provider keys
     (just `load_config_file(member / 'repolish.yaml').providers.keys()`).
   - Build a `MemberInfo`.
7. Return a `MonorepoContext(mode="root", root_dir=config_dir, members=[...])`.

**`detect_monorepo_from_config(config_dir: Path, monorepo_config: MonorepoConfig) -> MonorepoContext | None`**

Same as above but uses `monorepo_config.members` instead of reading
`[tool.uv.workspace]`. This is the path when the user explicitly declares
members in `repolish.yaml`.

**`check_running_from_member(config_dir: Path) -> Path | None`**

Walk parent directories looking for a `pyproject.toml` that contains
`[tool.uv.workspace]` whose expanded member globs include `config_dir`.
Returns the root path if found (meaning we're inside a member), or `None`.

This implements the R10 guard. Keep it separate so it can be called early
in the CLI before any config loading happens.

### 2.2 — Integration test for detection

**File**: `tests/integration/test_monorepo_detection.py`

Create a fixture directory structure under `tests/integration/fixtures/`:

```
monorepo-basic/
├── pyproject.toml          # [tool.uv.workspace] members = ["packages/*"]
├── repolish.yaml           # root config with a simple provider
└── packages/
    ├── pkg-a/
    │   ├── pyproject.toml  # [project] name = "pkg-a"
    │   └── repolish.yaml   # providers: { simple-provider: ... }
    ├── pkg-b/
    │   ├── pyproject.toml  # [project] name = "pkg-b"
    │   └── repolish.yaml   # providers: { simple-provider: ... }
    └── pkg-no-repolish/
        └── pyproject.toml  # no repolish.yaml → silently skipped
```

Tests:
- `test_detect_monorepo_finds_members`: call `detect_monorepo` on the
  fixture root. Assert `mode="root"`, confirm `pkg-a` and `pkg-b` are
  members, confirm `pkg-no-repolish` is skipped.
- `test_detect_monorepo_standalone`: call on a non-monorepo fixture.
  Returns `None`.
- `test_detect_monorepo_explicit_members`: create a root `repolish.yaml`
  with `monorepo: { members: ["packages/pkg-a"] }`. Only `pkg-a` is
  discovered.
- `test_check_running_from_member`: `chdir` to `packages/pkg-a`, call
  `check_running_from_member`. Returns the root path.
- `test_check_running_from_member_at_root`: `chdir` to root, returns
  `None`.

---

## Phase 3: Dry Pass & Data Collection

The dry pass runs the provider pipeline for each member but stops before
writing any files. Its purpose is to collect two things that the root pass
needs: **`ProviderEntry` objects** (so root providers can see member
providers in `all_providers`) and **emitted inputs** (so member providers'
`provide_inputs` outputs can be routed to root providers).

### 3.1 — Add a dry-run mode to `_run_provider_pipeline`

**File**: `repolish/loader/orchestrator.py`

Add a `dry_run: bool = False` field to `PipelineOptions`:

```python
@dataclass(frozen=True)
class PipelineOptions:
    context_overrides: dict[str, object] | None = None
    provider_overrides: dict[str, dict[str, object]] | None = None
    alias_map: dict[str, str] | None = None
    global_context: GlobalContext = field(default_factory=GlobalContext)
    dry_run: bool = False  # NEW: skip file contributions when True
```

When `dry_run=True`, `_run_provider_pipeline` should:

1. Run the full context-and-inputs phase as normal (create_context →
   provide_inputs → finalize_context).
2. **Skip** `collect_provider_contributions` (no file_mappings, anchors,
   symlinks collected).
3. **Return** a richer result than just `Providers`. The dry pass needs to
   expose:
   - `provider_contexts` — finalized contexts per provider (as today).
   - `all_providers_list` — the `list[ProviderEntry]` built during the
     pipeline (already exists internally as a local variable; needs to be
     surfaced).
   - `emitted_inputs` — the raw `list[BaseInputs]` each provider returned
     from `provide_inputs()`, **before** routing. Currently
     `gather_received_inputs` both collects and routes in one pass; the
     dry-run path needs to also capture the pre-routing outputs.

One clean way to expose this: introduce a `DryRunResult` dataclass:

```python
@dataclass
class DryRunResult:
    provider_contexts: dict[str, BaseContext]
    all_providers_list: list[ProviderEntry]
    emitted_inputs: list[BaseInputs]  # flat list of all inputs from all providers
```

When `dry_run=True`, return this instead of `Providers`. The caller
(the monorepo orchestrator) uses it to build the root pass's extended
provider list and input pool.

**Changes to `gather_received_inputs`:** The function currently calls
`provide_inputs` on each provider and immediately routes via
`_distribute_payloads`. To capture raw outputs, either:
- Add an accumulator list that `_collect_for_provider` appends to before
  routing, or
- Split into two steps: `_collect_all_inputs` (returns flat list) and
  `_route_inputs` (does schema matching). The dry pass calls only the
  first; the normal pass calls both.

The second approach is cleaner and keeps `gather_received_inputs`
backward-compatible.

### 3.2 — Add `collect_member_data` helper

**File**: `repolish/commands/monorepo.py` — this module handles the
monorepo orchestration that coordinates multiple repolish runs.

```python
@dataclass
class MemberDryRunData:
    """Data collected from a single member's dry pass."""
    member_path: str               # repo-relative POSIX path
    provider_entries: list[ProviderEntry]
    emitted_inputs: list[BaseInputs]


def collect_member_data(
    members: list[MemberInfo],
    root_dir: Path,
    monorepo_ctx: MonorepoContext,
) -> list[MemberDryRunData]:
    """Run a dry provider pipeline for each member and collect data.

    For each member:
    1. chdir to the member directory.
    2. Load its repolish.yaml via load_config().
    3. Build provider directories list from the config.
    4. Build a GlobalContext with mode="package" for this member.
    5. Call create_providers(...) in dry_run mode.
    6. Collect the DryRunResult (entries + inputs).

    Returns a list of MemberDryRunData, one per member.
    """
```

This function temporarily changes the working directory (using a context
manager, not os.chdir) for each member so that providers that read
`pyproject.toml` or other relative-path resources work correctly.

Important: The `MonorepoContext` injected into these dry-pass providers
should have `mode="package"` and `package_dir=member_path`. This way
even during the dry pass, providers know they're in a package context.

### 3.3 — Extend root pass to accept member data

**File**: `repolish/loader/orchestrator.py`

Add two new optional fields to `PipelineOptions`:

```python
@dataclass(frozen=True)
class PipelineOptions:
    ...
    extra_provider_entries: list[ProviderEntry] | None = None
    extra_inputs: list[BaseInputs] | None = None
```

In `_run_provider_pipeline`, when these are set:

- **After** `_build_all_providers_list`: extend `all_providers_list` with
  `extra_provider_entries`. This means every root provider's
  `provide_inputs` and `finalize_context` sees member entries in
  `all_providers`.
- **During** input routing: inject `extra_inputs` into the routing pool
  alongside root providers' own `provide_inputs` outputs. The standard
  `_distribute_payloads` / `_schema_matches` logic delivers them to
  root providers whose schemas accept them.

This is the only place the member/root boundary is crossed. The rest of
the pipeline is unchanged.

### 3.4 — Integration test for dry pass

**File**: `tests/integration/test_monorepo_dry_pass.py`

Use the `monorepo-basic` fixture from Phase 2 plus installed test
providers. Tests:

- `test_dry_pass_collects_entries_and_inputs`: Run `collect_member_data`
  for the fixture. Assert that the returned list has entries for both
  `pkg-a` and `pkg-b`. For each member, assert `provider_entries` contains
  an entry with `alias="simple-provider"` and the correct context type.
  Assert `emitted_inputs` contains the expected `BaseInputs` subclass
  instances (whatever `SimpleProvider.provide_inputs` returns).

- `test_dry_pass_provider_inputs_flow`: Create a two-provider fixture
  where provider A emits inputs to provider B. Run dry pass. Assert that
  B's finalized context reflects the data from A (proving the full
  provide_inputs → finalize_context pipeline ran within the member).
  Also assert the emitted inputs from A are captured in the dry run result.

- `test_dry_pass_does_not_write_files`: Run dry pass. Assert no files
  were written to the member directories (no `.repolish/`, no rendered
  files).

- `test_root_pass_receives_member_inputs`: Set up a root pass with
  `extra_provider_entries` and `extra_inputs` from a member dry pass.
  Assert that the root provider's `finalize_context` receives the
  member-emitted inputs in `received_inputs`. This is the critical test
  that proves the member-to-root routing works.

---

## Phase 4: Monorepo Orchestrator

### 4.1 — Create `repolish/commands/monorepo.py`

This is the main orchestration module. One public function:

**`run_monorepo(config_path: Path, *, check_only: bool, strict: bool = False, member: str | None = None, root_only: bool = False) -> int`**

Flow:

```python
def run_monorepo(config_path, *, check_only, strict=False, member=None, root_only=False):
    config_dir = config_path.resolve().parent

    # 1. Detect monorepo
    raw_config = load_config_file(config_path)
    if raw_config.monorepo and raw_config.monorepo.members:
        mono_ctx = detect_monorepo_from_config(config_dir, raw_config.monorepo)
    else:
        mono_ctx = detect_monorepo(config_dir)

    if mono_ctx is None:
        # Not a monorepo, delegate to single-pass command
        return apply_command(config_path, check_only=check_only, strict=strict)

    # 2. If --member <path>, validate the member exists
    if member:
        matching = [m for m in mono_ctx.members if str(m.path) == member or m.name == member]
        if not matching:
            error and exit
        target_members = matching
    else:
        target_members = mono_ctx.members

    # 3. Dry pass: collect all member data (entries + inputs)
    #    Always run, even when --root-only, because root providers need
    #    member inputs routed to them.
    member_data = collect_member_data(mono_ctx.members, config_dir, mono_ctx)

    # 4. Aggregate member data for root pass injection
    all_member_entries = [e for md in member_data for e in md.provider_entries]
    all_member_inputs = [i for md in member_data for i in md.emitted_inputs]

    # 5. Root pass (unless --member was specified)
    root_mono_ctx = MonorepoContext(
        mode="root",
        root_dir=config_dir,
        members=mono_ctx.members,
    )
    if not member:
        # Inject root_mono_ctx into GlobalContext AND pass member data
        # into the pipeline via extra_provider_entries / extra_inputs
        rc = _run_single_pass(
            config_path, root_mono_ctx,
            check_only=check_only, strict=strict,
            extra_provider_entries=all_member_entries,
            extra_inputs=all_member_inputs,
        )
        if rc != 0:
            return rc

    # 6. Member passes (unless --root-only)
    if not root_only:
        for m in target_members:
            member_mono_ctx = MonorepoContext(
                mode="package",
                root_dir=config_dir,
                package_dir=config_dir / m.path,
                members=mono_ctx.members,
            )
            member_config = config_dir / m.path / 'repolish.yaml'
            rc = _run_single_pass(member_config, member_mono_ctx, check_only=check_only, strict=strict)
            if rc != 0:
                return rc

    return 0
```

### 4.2 — `_run_single_pass` helper

This is a thin wrapper that sets up the execution context for a single
repolish pass:

1. Change working directory to the config's parent dir.
2. Build a `GlobalContext` with the supplied `MonorepoContext`.
3. Call into the existing `apply.command()` — but we need a way to pass
   the pre-built `GlobalContext` AND the member data into the pipeline.
   See 4.3.

For the root pass, `extra_provider_entries` and `extra_inputs` are
forwarded. For member passes, these are `None` (member passes are fully
isolated — no cross-member input injection).

### 4.3 — Thread `GlobalContext` / `MonorepoContext` through the pipeline

Currently `get_global_context()` is called inside
`repolish/loader/orchestrator.py` → `create_providers()` and builds a
fresh `GlobalContext` from the git remote. We need to allow passing a
pre-built `GlobalContext` into `apply.command()`.

**Option A (recommended)**: Add optional parameters to `apply.command()`:
- `global_context: GlobalContext | None = None`
- `extra_provider_entries: list[ProviderEntry] | None = None`
- `extra_inputs: list[BaseInputs] | None = None`

When provided, pass them through to `build_final_providers` →
`create_providers`. The existing `create_providers` already passes
`global_ctx_obj` into `PipelineOptions`; we just need to accept these
parameters and forward them.

Changes:
- `apply.command()`: accept optional `global_context`,
  `extra_provider_entries`, and `extra_inputs` parameters.
- `hydration/context.py` → `build_final_providers()`: accept and forward
  the same optional parameters to `create_providers`.
- `loader/orchestrator.py` → `create_providers()`: accept optional
  `global_context`, `extra_provider_entries`, `extra_inputs`. When
  `global_context` is `None`, call `get_global_context()` as today.
  Pass `extra_provider_entries` and `extra_inputs` into `PipelineOptions`
  so `_run_provider_pipeline` can inject them.

This is a small, backward-compatible threading of parameters through
three function signatures. All parameters default to `None`, so existing
callers (standalone mode) are unaffected.

### 4.4 — Hook into `apply.command()` (or the CLI layer)

The CLI entry point for `repolish apply` currently calls `apply.command()`
directly. With monorepo support, the CLI should first check for monorepo
conditions and delegate to `run_monorepo()` when appropriate.

Modify the CLI handler (likely in `repolish/cli/main.py` or wherever
`apply` is wired up):

```python
def apply_cli_handler(...):
    config_path = Path('repolish.yaml')

    # R10 guard: are we inside a member?
    if not standalone_flag:
        parent_root = check_running_from_member(config_path.resolve().parent)
        if parent_root:
            error(f"this directory is a member of a monorepo rooted at {parent_root}. "
                  f"Run `repolish apply` from the root, or use "
                  f"`repolish apply --member {Path.cwd().name}` from the root.")
            return 1

    # Monorepo detection
    if standalone_flag:
        # --standalone: run single-pass for this directory only, same as
        # running repolish at the root with --member targeting this package
        return apply.command(config_path, check_only=check_only, strict=strict)

    return run_monorepo(
        config_path,
        check_only=check_only,
        strict=strict,
        member=member_flag,
        root_only=root_only_flag,
    )
```

When `run_monorepo` detects the repo is not actually a monorepo, it falls
back to the single-pass `apply.command()` internally.

---

## Phase 5: CLI Flags

### 5.1 — Add flags to `repolish apply`

**File**: wherever the `apply` typer/click command is defined.

New flags:
- `--root-only`: skip member passes, run only the root pass. Mutually
  exclusive with `--member`.
- `--member <path>`: run only the specified member's full pass (with the
  full monorepo context — the dry pass still runs for all members so
  member inputs are available if needed). The root pass is skipped. Accepts either the repo-relative path
  (`packages/pkg-a`) or the package name (`pkg-a`). Only one member at a
  time.
- `--standalone`: bypass monorepo detection entirely. Run a normal
  single-pass repolish on the current directory. This is the escape hatch
  for R10 — if you're in a member directory and pass `--standalone`, it
  runs as if the parent monorepo doesn't exist.

These flags are only for `repolish apply`. `repolish preview` and
`repolish lint` are development tools and don't need monorepo orchestration
at this time.

### 5.2 — R10 guard implementation

**Where**: early in the CLI handler, before any config loading.

Call `check_running_from_member(cwd)`. If it returns a root path and
`--standalone` was not passed, exit with the error message from the
requirements doc. The `--standalone` flag suppresses this check.

When `--standalone` is active, the behaviour is identical to applying
repolish from the root targeting only the current directory: single-pass,
no monorepo context, `mode="standalone"`.

---

## Phase 6: Integration Tests — End-to-End

All tests in this phase go under `tests/integration/`. They use the
existing `FixtureRepo` / `InstalledProviders` / `run_repolish` machinery.

### 6.1 — Create test fixtures

**Fixture: `monorepo-basic`** (from Phase 2, reused here)

```
tests/integration/fixtures/monorepo-basic/
├── pyproject.toml          # [tool.uv.workspace] members = ["packages/*"]
├── repolish.yaml           # providers: { simple-provider: { cli: simple-provider-link } }
└── packages/
    ├── pkg-a/
    │   ├── pyproject.toml
    │   ├── repolish.yaml   # providers: { simple-provider: { cli: simple-provider-link, context_overrides: { greeting: "hello from pkg-a" } } }
    │   └── README.md       # optional seed file
    ├── pkg-b/
    │   ├── pyproject.toml
    │   ├── repolish.yaml   # providers: { simple-provider: { cli: simple-provider-link, context_overrides: { greeting: "hello from pkg-b" } } }
    │   └── README.md
    └── pkg-no-repolish/
        └── pyproject.toml
```

**Fixture: `monorepo-cross-provider`** (for testing member-to-root inputs)

This requires two providers that communicate via inputs:

1. A **member provider** that emits a typed input (e.g.
   `MonoRootInputs(greeting="hello from pkg-a")`) via `provide_inputs`.
2. A **root provider** that declares `get_inputs_schema() -> MonoRootInputs`
   and absorbs those inputs in `finalize_context`, then uses the data in
   `create_file_mappings` to generate a summary file.

Recommendation: create a `monorepo-root-provider` in `provider-examples/`
that acts as the root aggregator, and a `monorepo-member-provider` (or
extend `simple-provider`) that emits inputs targeting the root provider's
schema.

```python
# monorepo-root-provider: aggregates member inputs at the root
class MonoRootInputs(BaseInputs):
    greeting: str = ''
    member_path: str = ''

class MonoRootProvider(Provider[MonoRootCtx, MonoRootInputs]):
    def finalize_context(self, own_context, received_inputs, all_providers, provider_index):
        # received_inputs contains MonoRootInputs from member providers
        own_context.member_greetings = [
            f"{inp.member_path}: {inp.greeting}" for inp in received_inputs
        ]
        return own_context

    def create_file_mappings(self, context):
        if context.repolish.monorepo.mode == "root":
            # Generate a summary file from the aggregated member greetings
            return {"members-summary.txt": TemplateMapping(...)}
        return {}
```

```python
# member provider: emits MonoRootInputs for the root provider
class MemberProvider(Provider[MemberCtx, BaseModel]):
    def provide_inputs(self, own_context, all_providers, provider_index):
        return [MonoRootInputs(
            greeting=own_context.greeting,
            member_path=str(own_context.repolish.monorepo.package_dir or ''),
        )]
```

The exact implementation depends on what's easiest within the existing
`TemplateMapping` / file_mappings API.

### 6.2 — Register fixtures in conftest

**File**: `tests/integration/conftest.py`

Add new `FixtureRepo` entries to the `Fixtures` dataclass and
`Fixtures.from_dir`. Wire up them in the session fixture.

### 6.3 — Test cases

**File**: `tests/integration/test_monorepo.py`

Each test case is described as a `TCase` dataclass per project convention.

**Test: `test_standalone_mode_unchanged`**
- Use the existing `simple-repo` fixture (not a monorepo).
- Run `repolish apply`.
- Assert everything works exactly as before.
- Optionally: verify that `repolish.monorepo.mode` is `"standalone"` in
  the provider context (read the debug JSON from
  `.repolish/_/provider-context.*.json`).

**Test: `test_monorepo_root_pass_creates_root_files`**
- Use `monorepo-basic`.
- Run `repolish apply --root-only`.
- Assert root-level files are created. Assert no files in `packages/pkg-a/`
  or `packages/pkg-b/`.

**Test: `test_monorepo_member_pass_creates_member_files`**
- Use `monorepo-basic`.
- Run `repolish apply --member packages/pkg-a`.
- Assert files created in `packages/pkg-a/`. Assert no root-level files.
  Assert no files in `packages/pkg-b/`.

**Test: `test_monorepo_full_run_all_passes`**
- Use `monorepo-basic`.
- Run `repolish apply` (no flags).
- Assert root-level files exist. Assert `packages/pkg-a/` and
  `packages/pkg-b/` both have their files. Assert `packages/pkg-no-repolish/`
  is untouched.

**Test: `test_monorepo_member_isolation`**
- Use `monorepo-basic` with different `context_overrides` per member.
- Run full apply. Read `packages/pkg-a/README.simple-provider.md` and
  `packages/pkg-b/README.simple-provider.md`. Assert each contains its
  own greeting, proving contexts are isolated.

**Test: `test_monorepo_local_repolish_dir`**
- Run full apply. Assert `.repolish/` exists at root, at `packages/pkg-a/`,
  and at `packages/pkg-b/`. Assert none of the `.repolish/` dirs contain
  `../../` paths.

**Test: `test_monorepo_root_provider_receives_member_inputs`**
- Use `monorepo-cross-provider` fixture.
- Run `repolish apply` (or `--root-only`).
- Assert root generated file contains data from both members' inputs.
  This proves the dry-pass → emitted inputs → root routing → finalize_context
  chain works end-to-end.

**Test: `test_monorepo_post_process_per_pass`**
- Add `post_process: ["touch .post-processed"]` to root and member
  repolish.yaml files.
- Run full apply.
- Assert `.post-processed` exists in root, `packages/pkg-a/`, and
  `packages/pkg-b/`.

**Test: `test_guard_running_from_member`**
- Stage `monorepo-basic`. `chdir` to `packages/pkg-a/`.
- Run `repolish apply`. Assert non-zero exit code and error message
  mentioning the root path.

**Test: `test_standalone_flag_bypasses_guard`**
- Same setup as above. Run `repolish apply --standalone`.
- Assert success. Files created in `packages/pkg-a/` only.
  `mode="standalone"`.

**Test: `test_explicit_members_in_config`**
- Create a variant fixture where root `repolish.yaml` has
  `monorepo: { members: ["packages/pkg-a"] }`.
- Run full apply. Assert only `pkg-a` is linked as a member. `pkg-b` is
  ignored even though it has a `repolish.yaml`.

---

## Phase 7: Documentation

### 7.1 — Monorepo guide

**File**: `docs/guides/monorepo.md`

Sections:
1. **Quick start** — minimal setup for uv workspace users.
2. **How it works** — detection, discovery, execution order.
3. **Accessing monorepo context in providers** — `context.repolish.monorepo`.
4. **Writing mode-aware providers** — the `if mode == "root"` pattern.
5. **CLI flags** — `--root-only`, `--member`, `--standalone`.
6. **Explicit member configuration** — `monorepo.members` in repolish.yaml.

### 7.2 — Update provider authoring docs

Show the recommended branching pattern from R5:

```python
def create_file_mappings(self, context):
    mode = context.repolish.monorepo.mode
    if mode == "root":      return self._root_mappings(context)
    if mode == "package":   return self._package_mappings(context)
    return self._standalone_mappings(context)
```

---

## Summary of Files Changed/Created

### New files
| File | Purpose |
|------|---------|
| `repolish/config/monorepo.py` | Detection, discovery, `check_running_from_member` |
| `repolish/commands/monorepo.py` | `run_monorepo`, `collect_member_data`, `_run_single_pass` |
| `tests/integration/fixtures/monorepo-basic/` | Fixture directory tree |
| `tests/integration/fixtures/monorepo-cross-provider/` | Fixture for member-to-root input routing |
| `tests/integration/test_monorepo_detection.py` | Detection integration tests |
| `tests/integration/test_monorepo_dry_pass.py` | Dry pass integration tests |
| `tests/integration/test_monorepo.py` | End-to-end integration tests |
| `provider-examples/monorepo-root-provider/` | Test provider that consumes member inputs at the root |
| `docs/guides/monorepo.md` | User-facing documentation |

### Modified files
| File | Change |
|------|--------|
| `repolish/loader/models/context.py` | Add `MemberInfo`, `MonorepoContext`, `monorepo` field on `GlobalContext` |
| `repolish/config/models/project.py` | Add `MonorepoConfig`, `monorepo` field on `RepolishConfigFile` |
| `repolish/loader/pipeline.py` | Add `dry_run`, `extra_provider_entries`, `extra_inputs` to `PipelineOptions` |
| `repolish/loader/orchestrator.py` | Respect `dry_run` in `_run_provider_pipeline`; inject `extra_provider_entries` into `all_providers` and `extra_inputs` into routing; accept optional `global_context` in `create_providers` |
| `repolish/loader/exchange.py` | Split `gather_received_inputs` to expose raw emitted inputs before routing |
| `repolish/hydration/context.py` | Thread optional `global_context`, `extra_provider_entries`, `extra_inputs` through `build_final_providers` |
| `repolish/commands/apply.py` | Accept optional `global_context` + member data params, delegate to monorepo orchestrator |
| CLI entry point | Add `--root-only`, `--member`, `--standalone` flags; R10 guard |
| `tests/integration/conftest.py` | Register new fixtures |

### Unchanged
- `Provider` class — **no new methods**. The public API stays exactly as it
  is.
- All existing tests — must continue passing. `MonorepoContext` defaults to
  standalone mode so nothing changes.
- `provide_inputs` / `finalize_context` / `create_file_mappings` — same
  signatures, same behaviour.

---

## Suggested Implementation Order

Work phase-by-phase. Each phase should be a separate PR or at minimum a
separate commit boundary so we can verify nothing regresses.

1. **Phase 1** (models) — smallest, most self-contained. Should be done
   first and verified with `poe ci-checks`.
2. **Phase 2** (detection) — depends on Phase 1 models. First integration
   tests land here.
3. **Phase 3** (dry pass + root injection) — depends on Phase 2. This is
   the key innovation — reusing the existing pipeline to collect member
   provider entries and emitted inputs, then injecting them into the root
   pass's routing.
4. **Phase 4** (orchestrator) — depends on Phase 3. This is the largest
   phase but is mostly wiring: calling existing functions in a loop.
5. **Phase 5** (CLI) — depends on Phase 4. Thin layer.
6. **Phase 6** (integration tests) — depends on Phase 5. Some tests can
   land earlier alongside their respective phases.
7. **Phase 7** (docs) — can be done last or incrementally.
