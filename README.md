# repolish

> Repolish is a hybrid of templating and diff/patch systems, useful for
> maintaining repo consistency while allowing local customizations. It uses
> templates with placeholders that can be filled from a context, and regex
> patterns to preserve existing local content in files.

## Why this exists

Teams often need to enforce repository-level conventions (CI config, build
tools, metadata, common docs) while letting individual projects keep local
customizations. The naive approaches are painful:

- Copying templates into many repos means drift over time and manual syncs.
- Running destructive templating can overwrite local changes developers rely on.

Repolish solves this by combining templating (to generate canonical files) with
a set of careful, reversible operations that preserve useful local content.
Instead of blindly replacing files, Repolish can:

- Fill placeholders from provider-supplied context.
- Apply anchor-driven replacements to keep developer-customized sections.
- Track provider-specified deletions and record provenance so reviewers can see
  _why_ a path was requested for deletion.

## Design overview

Key concepts:

- Providers (templates): Each provider lives in a template directory and may
  include a `repolish.py` module that exports `create_context()`,
  `create_anchors()`, and/or `create_delete_files()` helpers. Providers supply
  cookiecutter context and may indicate files that should be removed from a
  project.
- Anchors: A small markup syntax placed in templates (and optionally in project
  files) that marks blocks or regex lines to preserve. Examples:
  - Block anchors: `## repolish-start[readme]` ... `repolish-end[readme]`
  - Regex anchors: `## repolish-regex[keep]: ^important=.*` The processors use
    these anchors to replace or merge the template content with the local
    project file while preserving the parts marked with anchors.
- Delete semantics: Providers can request deletions using POSIX-style paths. A
  `!` prefix acts as a negation (keep). Config-level `delete_files` are applied
  last and recorded in provenance.
- Provenance: Repolish records a `delete_history` mapping that stores, for each
  candidate path, a list of decisions (which provider or config requested a
  delete or a keep). This helps reviewers and automation understand why a path
  was flagged.

## How it works (high level)

1. Load providers configured in `repolish.yaml` (or the default config).
2. Merge provider contexts; config-level context overrides provider values.
3. Merge anchors from providers and config.
4. Stage all provider template directories into a single cookiecutter template
   (adjacent to the config under `.repolish/setup-input`).
5. Preprocess staged templates by applying anchor-driven replacements using
   local project files (looked up relative to the config location).
6. Render the merged cookiecutter template once into `.repolish/setup-output`.
7. In `--check` mode: compare generated files to project files and report either
   diffs, missing files, or paths that providers wanted deleted but which are
   still present.
8. In apply mode: copy generated files into the project and apply deletions as
   the final step.

## Example usage

repolish.yaml (simple example):

```yaml
directories:
  - ./templates/template_a
  - ./templates/template_b
context: {}
anchors: {}
delete_files: []
```

Run a dry-run check (useful for CI):

```bash
repolish --check --config repolish.yaml
```

This will produce structured logs that include:

- The merged provider `context` and `delete_paths` (so you can see what was
  requested).
- A `check_result` listing per-path diffs or deletion warnings like
  `PRESENT_BUT_SHOULD_BE_DELETED`.

## Processor story (anchors)

We iterated on preserving local file semantics and landed on a simple, explicit
anchor-based system. Anchors are easy for template authors to add and for
maintainers to reason about:

- Block anchors allow entire sections of a file to be preserved or replaced
  while keeping the surrounding template-driven structure.
- Regex anchors can mark single lines or patterns to keep (useful for
  maintainer-inserted keys or comments that should survive templating).

Anchors are processed in staging before cookiecutter runs, so the generated
output already reflects local overrides while still taking canonical values from
templates when needed.

## How do I add anchors?

Anchors are intentionally simple so template authors and maintainers can reason
about them easily. There are two primary forms:

- Block anchors mark a named section to preserve or replace between
  `repolish-start[...]` and `repolish-end[...]` markers. Use them for multi-line
  sections such as README snippets, install blocks, or long descriptions.
- Regex anchors mark single-line patterns to keep using a regular expression.
  They are useful when you want to preserve a line that follows a predictable
  pattern (version lines, keys, simple single-line edits).

Below are two practical examples you can copy into templates and projects.

Dockerfile (block anchor)

Template (templates/template_a/Dockerfile):

```dockerfile
# base image
FROM python:3.11-slim

## repolish-start[install]
# install system deps
RUN apt-get update && apt-get install -y build-essential libssl-dev
## repolish-end[install]

# copy + install python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir .
```

Project Dockerfile (local override) — developer has custom install needs:

```dockerfile
FROM python:3.11-slim

## repolish-start[install]
# custom build deps for project X
RUN apt-get update && apt-get install -y locales libpq-dev
## repolish-end[install]

# copy + install python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir .
```

When Repolish runs its preprocessing, the `install` block from the local project
will be preserved in the staged template (so the generated output keeps the
local custom `RUN` command), while the rest of the Dockerfile comes from the
template.

pyproject.toml (regex anchor + block anchor)

Template (templates/template_a/pyproject.toml):

```toml
[tool.poetry]
name = "{{ cookiecutter.package_name }}"
version = "0.1.0"
## repolish-regex[keep]: ^version\s*=\s*".*"

description = "A short description"

## repolish-start[extra-deps]
# optional extra deps (preserved when present)
## repolish-end[extra-deps]
```

Project pyproject.toml (developer bumped version and added extras):

```toml
[tool.poetry]
name = "myproj"
version = "0.2.0"

description = "Local project description"

## repolish-start[extra-deps]
requests = "^2.30"
## repolish-end[extra-deps]
```

In this example the `## repolish-regex[keep]: ^version\s*=\s*".*"` anchor
ensures the local `version = "0.2.0"` line is preserved instead of being
replaced by the template's `0.1.0`. The `extra-deps` block is preserved
whole-cloth when present, letting projects keep local dependency additions.

Notes and tips

- Use meaningful anchor names (e.g., `install`, `readme`, `extra-deps`) so
  reviewers immediately understand the preserved section's intent.
- Regex anchors are applied line-by-line; prefer anchoring to a simple, easy to
  read pattern to avoid surprises.
- Anchors are processed before cookiecutter rendering, so template substitutions
  still work around preserved sections.

### Where anchors are declared and uniqueness

Anchors can come from three places (and are merged in this order):

1. Provider templates: any `## repolish-start[...]` / `## repolish-regex[...]`
   markers present inside the provider's template files.
2. Provider code: a provider's `create_anchors()` callable can return an anchors
   mapping (key -> replacement text) used during preprocessing.
3. Config-level anchors: the `anchors` mapping in `repolish.yaml` applies last
   and can be used to override or add anchor values.

When anchors are merged, later sources override earlier ones (config wins).
Anchor keys must be unique across the whole merged template set — keys are
global identifiers used to find matching `repolish-start[...]` blocks or
`repolish-regex[...]` declarations. If two different template files (or
providers) use the same anchor key, the later provider's value will override the
earlier one, which can produce surprising results.

Example conflict

Two provider templates accidentally use the same anchor key `init`:

- `templates/a/Dockerfile` contains `## repolish-start[init]` …
  `## repolish-end[init]`
- `templates/b/README.md` also contains `## repolish-start[init]` …
  `## repolish-end[init]`

Because anchor keys are merged globally, the `init` block from the provider that
is processed later will replace (or be used in place of) the other one. That may
not be what you want — for predictable behavior, choose anchor keys scoped to
the file or the provider, e.g. `docker-install` or `readme-intro`.

Best practice: prefix anchor keys with the file or provider name when the
content is file-scoped. This avoids accidental collisions when multiple
providers contribute templates that contain similarly-named sections.

## Why this is useful

- Safe consistency: teams get centralized templates without forcing destructive,
  manual rollouts.
- Clear explainability: the `delete_history` provenance makes it easy to review
  why a file was targeted for deletion or kept.
- CI-friendly: `--check` can be run in CI to detect drift; logs and diffs make
  it straightforward to require PRs to run repolish before merging.

## Final notes

Repolish is intentionally small and composable. If you need per-file log
artifacts, or slightly different merge rules, the processors and cookiecutter
helpers are isolated so you can adapt them safely.

Contributions and issues are welcome — see the test-suite for practical examples
of how the system behaves.
