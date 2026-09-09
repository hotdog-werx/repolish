# Pause a File

`paused_files` is the fastest way to tell repolish to leave a file alone. It is
designed for temporary situations: a provider shipped a bad update, a migration
is in progress, or you just need to ship today and deal with it later.

## How to use it

Add the file path to `paused_files` in your `repolish.yaml`:

```yaml
paused_files:
  - .github/workflows/ci.yml
```

That is the whole change. On the next `repolish --check` or `repolish apply`
that file will be silently skipped — no diff, no apply, no failure.

## What it does (and does not do)

| Behaviour       | Detail                                                                                                       |
| --------------- | ------------------------------------------------------------------------------------------------------------ |
| `--check`       | File is excluded from comparison. No diff is reported even if the provider would generate different content. |
| `apply`         | File is not written. Your local copy is untouched.                                                           |
| `link`          | Provider resource `copies` targeting the file are skipped too — a paused copy keeps your local edits.        |
| `delete_files`  | If a provider requested the file be deleted, the deletion is also skipped.                                   |
| Everything else | All other files continue to be managed normally.                                                             |

Pausing also protects **copied files** — files a provider materialises via
`copies` because they must not be Jinja-interpreted (JSON configs, WASM plugins,
…). Repolish skips re-copying those while the entry stays in `paused_files`.
Provider **symlinks** are not affected: they stay links to provider resources
and are not meant to be edited locally in the first place.

Pausing a file does **not** remove the provider's template. When you unpause the
file, repolish will resume comparing and applying it on the next run.

## Multiple files

```yaml
paused_files:
  - .github/workflows/ci.yml
  - pyproject.toml # provider migration pending
  - docs/CONTRIBUTING.md
```

## Leave a comment

`paused_files` entries are easy to forget. Leave a short note explaining why the
file is paused and link to a ticket or PR if there is one:

```yaml
paused_files:
  # provider#42 — ruff config format change not yet merged
  - ruff.toml
```

## When to unpause

Remove the entry once the underlying provider issue is resolved and you have run
`repolish apply` to pull in the updated file. Leaving entries in `paused_files`
indefinitely defeats the purpose of using repolish to keep files consistent.

## Suppress vs pause

`paused_files` is temporary. If you want to permanently exclude a file from all
providers, use [`template_overrides`](template-overrides.md) with a `null` value
instead.

For **resource copies** the permanent equivalent is `overrides.copies` on the
provider entry: it disables a single copy target without replacing the
provider's whole copy list (and without the paused warning repolish emits for
`paused_files`):

```yaml
providers:
  mylib:
    cli: mylib-link
    overrides:
      copies:
        # project owns this file now — repolish never re-copies it
        dprint.json: false
```

This works on top of both the provider's `create_default_copies` declarations
and an explicit `copies:` list. Use it when the project — not the provider —
should own the file long-term.
