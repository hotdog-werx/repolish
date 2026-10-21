# repolish apply

Apply templates to the project. This is the main day-to-day command.

```
repolish apply [OPTIONS]
```

## Options

| Option                     | Default         | Description                                                                                                                                                                                                                            |
| -------------------------- | --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--config PATH`, `-c PATH` | `repolish.yaml` | Path to the repolish YAML configuration file.                                                                                                                                                                                          |
| `--check`                  | off             | Dry-run mode - load config and create context but do not write any files.                                                                                                                                                              |
| `--strict`                 | off             | Exit 1 if any provider could not be registered. Recommended for CI.                                                                                                                                                                    |
| `--standalone`             | off             | Bypass monorepo detection entirely and run a normal single-pass apply. Useful when running from inside a member package directory that is also a standalone project.                                                                   |
| `--root-only`              | off             | Run only the root pass; skip member passes. Mutually exclusive with `--member`.                                                                                                                                                        |
| `--member NAME`            | -               | Run only the named member's full pass (repo-relative path or package name). The root pass is skipped. Mutually exclusive with `--root-only`.                                                                                           |
| `--skip-post-process`      | off             | Skip all `post_process` commands defined in `repolish.yaml`.                                                                                                                                                                           |
| `--providers LIST`, `-p`   | -               | Comma-separated list of provider aliases to load. Only the listed providers are executed. Useful for faster iteration in monorepos. Note that providers dependent on inputs from filtered-out providers may produce incomplete output. |

## What it does

`repolish apply` runs the full pipeline:

1. **Registration pass** - every provider listed in `repolish.yaml` is
   registered (or re-registered if its cached paths are stale).
2. **Context pass** - each provider's `create_context()` is called, then
   `provide_inputs()` and `finalize_context()` run to exchange cross-provider
   data. A hook that raises is recorded and skipped, never fatal: the run
   continues with that provider incomplete and reports it in the summary tree
   (see `providers.md` for the exact skip semantics).
3. **Render pass** - templates are rendered against the merged context and
   written to disk, respecting file modes (`create-only`, `keep`, `delete`).
4. **Post-process pass** - any `post_process` shell commands from
   `repolish.yaml` are executed in order.

## Check mode

`--check` stops after the context pass. No files are written. Use it to validate
that all providers load and produce a context without running a full apply:

```bash
repolish apply --check
```

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
