# repolish apply

Apply templates to the project. This is the main day-to-day command.

```
repolish apply [OPTIONS]
```

## Arguments

The table below is generated from the apply parameter model in the CLI code, so
it cannot drift.

<!-- repolish:on:options cli-options apply -->

| Argument                        | Default         | Description                                                                                                                                  |
| ------------------------------- | --------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `--config PATH`, `-c PATH`      | `repolish.yaml` | Path to the repolish YAML configuration file                                                                                                 |
| `--check`                       | `False`         | Report drift and symlink issues without writing anything                                                                                     |
| `--fail-on-warnings`            | `False`         | Treat validator warnings as fatal errors (useful for CI)                                                                                     |
| `--skip-post-process`           | `False`         | Skip all post_process commands defined in repolish.yaml                                                                                      |
| `--strict`                      | `False`         | Exit with an error if any provider could not be registered (useful for CI)                                                                   |
| `--root-only`                   | `False`         | Run only the root pass; skip member passes (mutually exclusive with --member)                                                                |
| `--member VALUE`                | `None`          | Run only the specified member full pass (repo-relative path or package name). The root pass is skipped. Mutually exclusive with --root-only. |
| `--standalone`                  | `False`         | Bypass monorepo detection entirely and suppress the member note. Run a normal single-pass repolish on the current directory.                 |
| `--providers VALUE`, `-p VALUE` | `None`          | Comma-separated list of provider aliases to run (e.g., -p databricks,python)                                                                 |

<!-- repolish:off:options -->

## What it does

`repolish apply` runs the full pipeline:

1. **Registration pass** - every provider listed in `repolish.yaml` is
   registered (or re-registered if its cached paths are stale).
2. **Context pass** - each provider's `create_context()` is called, then
   `provide_inputs()` and `finalize_context()` run to exchange cross-provider
   data. A hook that raises is recorded and skipped: the run continues with that
   provider incomplete and reports it in the summary tree (see `providers.md`
   for the exact skip semantics). One exception: a failed `create_context()`
   leaves a context without provider identity, and when that provider owns files
   the render pass refuses to build their template namespace (see context
   soundness below) instead of writing headers with no provider name.
3. **Render pass** - templates are rendered against the merged context and
   written to disk, respecting file modes (`create-only`, `keep`, `delete`).
4. **Post-process pass** - any `post_process` shell commands from
   `repolish.yaml` are executed in order.

## Check mode

`--check` runs the whole pipeline but writes nothing to the project. Rendered
output is compared against the project tree and every declared symlink is
verified. The run exits 2 when files would change (drift) or a symlink is
missing, points somewhere other than its resource, or sits in a state apply
would replace:

```bash
repolish apply --check
```

The symlink check accepts whatever the machine's link chain can reach. A real
symlink or a Windows junction pointing at the resource counts everywhere. On a
machine that cannot create symlinks, files have no junction tier to fall back
on, so apply materialises a copy: a copy whose content matches the resource
passes, and one that drifted is reported as stale, which the next apply fixes by
re-copying. On machines that can create symlinks, a plain copy where a link
belongs is reported, since apply never produces one there.

## Context soundness

Two checks protect the run before any files are touched.

First, before the provider pipeline starts, every `module:` provider is audited
against the live environment. The run stops with an error when either check
fails:

- the module is not importable: the provider package is missing or broken, or
- the cached registration points somewhere other than where the environment
  imports the module: the package moved (a reinstall or an environment switch
  left the old location behind).

Either state renders generated headers with the alias instead of the package
identity, so the run refuses to start rather than write files from a broken
context. The error lists each affected provider with its recovery:

- run `repolish link` to re-register the provider at the module's current
  location
- when the module is not importable, re-run the environment setup first (the
  provider package needs a reinstall), then `repolish link`
- if linking cannot repair a provider, remove the `.repolish` directory and
  re-run the environment setup: every registration is rebuilt from scratch on
  the next run

`repolish link` runs the same audit after its refresh pass and exits 1 when a
provider is still unsound, with the same recovery steps in its report.

Second, the provider name is a guarded read. When the render pass builds a
template namespace, the provider name is read from the context
(`{{ repolish.provider.name }}`, the same value the generated header stamps) and
a context whose identity never resolved (package name, project name, and alias
all empty) stops the run there, with the observed values in the error. A valid
session always resolves at least the alias, so this error means a bug in
repolish or a broken provider context. Rendering happens inside the staging
tree, before anything is copied to the project, so the project stays untouched.
The check runs at the moment templates consume the context, so it covers custom
headers that read the name themselves, not only the built-in one.
`repolish
lint` is diagnostic and not guarded: it reports a broken provider's
findings and its recorded hook failures without stopping.

## Exit codes

The table below is generated from the exit-code contract in the apply session
code, so it cannot drift.

<!-- repolish:on:exit-codes exit-codes apply -->

| Code | Meaning                                                                                                                                              |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `0`  | The run completed: no validator, post-process, or hook failures. In check mode, also no drift.                                                       |
| `1`  | A validator failed, a post-process command failed, or a provider or facet hook raised and was skipped. In check mode, this outranks a drift finding. |
| `2`  | Check mode found drift: the project files differ from what apply would write. Apply mode never returns this.                                         |

<!-- repolish:off:exit-codes -->

Hook failures count as errors in both modes: the run finishes the remaining
work, prints each failure as a red `✗ <hook> failed` row with a `[details]` link
to its traceback report, and exits 1. A drift finding (exit 2) does not outrank
them: when both occur the exit code is 1.

## CI usage

Pass `--strict` so that a provider registration failure becomes a hard error
rather than a warning:

```yaml
# .github/workflows/ci.yaml
- run: repolish apply --strict
```

## Provider filtering

Use `--providers` (or `-p`) to load only a subset of providers. This is useful
for faster iteration when you know which providers need regeneration:

```bash
# Only run poe and ci-checks providers
repolish apply --providers poe,ci-checks

# Shorthand with -p
repolish apply -p poe,ci-checks
```

**Note:** Providers that depend on inputs from filtered-out providers may
produce incomplete output. This is an opt-in optimization for local development.

## Monorepo flags

In a monorepo repolish detects whether the current directory is the root or a
member and runs the appropriate passes automatically. The explicit flags let you
override this detection:

```bash
# Root pass only (skip all member re-runs)
repolish apply --root-only

# Re-run a single member without touching the root
repolish apply --member packages/my-lib

# Treat this directory as a standalone project regardless of monorepo detection
repolish apply --standalone
```
