# Repolish

A hybrid templating and diff/patch system for maintaining repository consistency
while preserving local customizations.

## Why this exists

Teams often need to enforce repository-level conventions — CI config, build
tools, metadata, shared docs — while letting individual projects keep local
customizations. The naive approaches are painful:

- Copying templates into many repos means drift over time and manual syncs.
- Running destructive templating can overwrite local changes developers rely on.

Repolish solves this by combining templating (to generate canonical files) with
a set of careful, reversible operations that preserve useful local content.
Instead of blindly replacing files, Repolish can:

- Fill placeholders from provider-supplied context.
- Apply anchor-driven replacements to keep developer-customized sections intact.
- Track provider-specified deletions and record provenance so reviewers can see
  why a path was requested for deletion.

## Key concepts

**Providers** supply templates and context. Each provider lives in a template
directory and may include a `repolish.py` module that exports
`create_context()`, `create_anchors()`, and/or `create_delete_files()` helpers.

**Anchors** are markers placed in templates (and optionally in project files)
that mark blocks or regex lines to preserve. Block anchors (`repolish-start` /
`repolish-end`) preserve entire sections; regex anchors (`repolish-regex`) keep
individual lines matching a pattern.

**File mappings** let providers conditionally select which template file to copy
to a given destination, allowing clean filenames without `{% if %}` clutter.

**Create-only files** are copied once on first run and skipped on subsequent
runs, making them ideal for initial scaffolding that users own after creation.

**Delete semantics** let providers request file removals. A `!` prefix negates
(keeps) a path. A `delete_history` provenance record is maintained so reviewers
can see why a path was flagged.

## How it works

1. Load providers configured in `repolish.yaml`.
2. Merge provider contexts; config-level context overrides provider values.
3. Merge anchors from providers and config.
4. Stage all provider template directories into a single merged template under
   `.repolish/setup-input`.
5. Preprocess staged templates by applying anchor-driven replacements using
   local project files.
6. Render the merged template into `.repolish/setup-output`.
7. In `--check` mode: compare generated files to project files and report diffs,
   missing files, or paths that providers wanted deleted but are still present.
8. In apply mode: copy generated files into the project and apply deletions.

## Why it is useful

- **Safe consistency**: teams get centralized templates without forcing
  destructive rollouts.
- **Clear explainability**: the `delete_history` provenance makes it easy to
  review why a file was targeted for deletion or kept.
- **CI-friendly**: `--check` detects drift; structured logs and diffs make it
  straightforward to require PRs to run repolish before merging.

---

!!! warning "Cookiecutter deprecation & migration (planned for v1)"

    Cookiecutter-based final rendering will be removed in the v1 release. You
    can migrate now by enabling the opt-in native Jinja renderer
    (`no_cookiecutter: true`) and validating your templates with
    `repolish preview`.

    **Why migrate**

    - Jinja avoids Cookiecutter CLI/option quirks (arrays treated as options),
      provides stricter validation (`StrictUndefined`) and clearer error
      messages, and enables new features such as `tuple`-valued `file_mappings`
      (per-file extra context).

    **Quick migration steps**

    1. Enable `no_cookiecutter: true` and run `repolish apply`.
    2. Update templates to prefer top-level context access
       (`{{ my_provider.* }}`) — the `cookiecutter` namespace remains available
       during migration.
    3. Follow the examples in the [Templates guide](guides/templates.md).

    See also: [Loader context](configuration/context.md) for `file_mappings`
    examples.

## Documentation

- [Installation](getting-started/installation.md)
- [Quick Start](getting-started/quick-start.md)
- [Configuration](configuration/overview.md)
- [Preprocessors](guides/preprocessors.md)
- [Templates](guides/templates.md)
- [Provider Patterns](guides/patterns.md)
- [CLI Commands](operations/cli.md)
