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

### Post-processing / formatters

Repolish supports an optional `post_process` list in `repolish.yaml` that runs
commands after the template is rendered but before the `--check` diff or apply
step. This is useful for running project formatters or other transformations so
the checks operate on formatted output.

How it runs

- The commands are executed exactly once after rendering and before checking or
  applying.
- Commands are executed with the working directory set to the rendered project
  folder inside `.repolish/setup-output/<project>` (where `_repolish_project` is
  the generated project folder name; default `repolish`).

Command forms

You can provide `post_process` entries in two forms:

-- string (e.g. "ruff --fix .") — the string is tokenized with shlex.split and
executed without a shell. This covers common tools and small python one-liners
like `python -c "open('file','w').write('x')"`.

- list/array of argv parts (e.g. `['prettier', '--write', '.']`) — recommended
  when you want to avoid any ambiguity about argument parsing and quoting.

Platform note

- On Windows the tokenization rules differ; Repolish uses Python's `shlex` to
  split string commands into argv lists before executing them without a shell.
  Because quoting/escaping differs between POSIX shells and Windows, prefer the
  argv/list form in `post_process` on Windows to avoid surprises. If you must
  provide a single string entry, keep arguments simple (no shell metacharacters)
  or call a committed script from the argv form.

Security note

We intentionally avoid running commands with `shell=True` to reduce shell
injection risks. If you need to run complex shell pipelines or use shell
metacharacters, create a small script (bash or python) in the repository and
invoke that script from `post_process` using the argv-list form. That keeps the
command execution explicit and avoids embedding complex shells in the
configuration.

Example `repolish.yaml` with formatters

```yaml
directories:
  - ./templates/template_a
context: {}
anchors: {}
post_process:
  - ['python', '-m', 'pip', 'install', '-r', 'requirements-dev.txt']
  - 'ruff --fix .'
  - ['prettier', '--write', 'src/']
delete_files: []
```

If a `post_process` command exits with a non-zero status, Repolish will fail and
return a non-zero exit code so CI can detect the problem.

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

## Conditional files (file mappings)

Template authors can provide multiple alternative files and conditionally choose
which one to copy based on the context. This is useful when you want to offer
different configurations (e.g., Poetry vs setuptools, GitHub Actions vs GitLab
CI) without cluttering filenames with cookiecutter's `{% if %}` syntax.

### How it works

Files in your template directory that start with `_repolish.` are treated as
**conditional/alternative files**. They will only be copied to the project if
explicitly referenced in the `create_file_mappings()` function (or
`file_mappings` variable) in your `repolish.py`.

The `file_mappings` return value is a dictionary where:

- **Keys** are destination paths in the final project (must be unique)
- **Values** are source paths in the template, or `None` to skip

Since this is Python code, you have full control over the logic used to select
source files (if/else, ternary expressions, function calls, etc.).

### Example

Template directory structure:

```
templates/my-template/
├── repolish.py
└── repolish/
    ├── README.md                          # Always copied
    ├── _repolish.github-workflow.yml      # Conditional
    ├── _repolish.gitlab-ci.yml            # Conditional
    ├── _repolish.poetry-pyproject.toml    # Conditional
    └── _repolish.setup-pyproject.toml     # Conditional
```

In `repolish.py`:

```python
def create_context():
    return {
        "use_github_actions": True,
        "use_poetry": False,
        "enable_precommit": True,
    }

def create_file_mappings():
    """Map destination paths to source files in the template.
    
    Returns dict[str, str | None]:
        - Key: destination path in final project
        - Value: source path in template, or None to skip
    
    Files starting with '_repolish.' are only copied when referenced here.
    """
    ctx = create_context()
    
    return {
        # Simple rename: always copy this conditional file
        ".github/workflows/ci.yml": "_repolish.github-workflow.yml",
        
        # Conditional: pick between alternatives based on context
        "pyproject.toml": (
            "_repolish.poetry-pyproject.toml" if ctx["use_poetry"]
            else "_repolish.setup-pyproject.toml"
        ),
        
        # Conditional: only include if enabled (None means skip)
        ".pre-commit-config.yaml": (
            "_repolish.precommit-config.yaml" if ctx.get("enable_precommit")
            else None
        ),
        
        # Could also use GitLab instead of GitHub
        ".gitlab-ci.yml": (
            "_repolish.gitlab-ci.yml" if ctx.get("use_gitlab")
            else None
        ),
    }
```

### Key behaviors

- **Conditional files** (prefixed with `_repolish.`) are **only** copied when
  explicitly listed in `file_mappings`
- **Regular files** (no `_repolish.` prefix) are always copied normally
- **Destinations are unique**: you cannot map multiple sources to the same
  destination within a single provider
- **None values are skipped**: returning `None` as the source means "don't copy
  this destination"
- **Multiple providers**: file_mappings from multiple providers are merged;
  later providers override earlier ones for the same destination

### Use cases

This feature is ideal for:

- Offering multiple CI configurations (GitHub Actions, GitLab CI, Jenkins)
- Supporting different build systems (Poetry, setuptools, Hatch)
- Providing optional configuration files that depend on context
- Keeping template filenames clean (no
  `{% if use_poetry %}pyproject.toml{% endif %}`)

The key advantage over cookiecutter's conditional filename syntax is that you
keep filenames clean and organize conditional logic in Python where you have
full programmatic control.

## Create-only files (initial scaffolding)

Template authors can specify files that should only be created when they don't
exist in the project. This is useful for initial repository scaffolding — like
setting up a package structure for a new project — where you want to create the
basic layout once but allow repolish to continue updating other files like
`pyproject.toml`, CI configs, etc.

### How it works

Files listed in `create_only_files` will be:

- **Created** if they don't exist in the project (normal template behavior)
- **Skipped** if they already exist (preserving user modifications)

This is different from anchors, which merge template and user content.
Create-only files are an all-or-nothing decision: create when missing, preserve
when present.

### Example: Scaffolding a new package

Imagine your template creates a Python package scaffold. When someone starts a
new project called `awesome-tool`, the template should create the package
structure once (directories, `__init__.py` files, example modules) but
subsequent repolish runs should only update the tooling files (like
`pyproject.toml`, `.github/workflows/ci.yml`, etc.) while leaving the package
code alone.

Template directory structure:

```
templates/python-project/
├── repolish.py
└── repolish/
    ├── src/
    │   └── {{cookiecutter.package_name}}/
    │       ├── __init__.py      # Create-only: initial package structure
    │       ├── py.typed          # Create-only: type marker
    │       └── main.py           # Create-only: example starter module
    ├── tests/
    │   ├── __init__.py           # Create-only: test package marker
    │   └── test_main.py          # Create-only: example test
    ├── pyproject.toml            # Regular: always updated by repolish
    └── .github/
        └── workflows/
            └── ci.yml            # Regular: always updated by repolish
```

In `repolish.py`:

```python
def create_context():
    return {
        "package_name": "awesome_tool",  # User's actual package name
        "project_name": "awesome-tool",
        "version": "0.1.0",
    }

def create_create_only_files():
    """Files that are created only if they don't exist.
    
    Returns list[str]:
        POSIX-style paths relative to project root
    
    Use this for initial scaffolding that creates the package structure
    but shouldn't be overwritten on subsequent repolish runs.
    """
    ctx = create_context()
    pkg = ctx["package_name"]
    
    return [
        # Package source structure (created once, then hands-off)
        f"src/{pkg}/__init__.py",
        f"src/{pkg}/py.typed",
        f"src/{pkg}/main.py",
        
        # Test structure (created once, then hands-off)
        "tests/__init__.py",
        "tests/test_main.py",
        
        # Project files users often customize
        ".gitignore",
        "README.md",  # If you want an initial README but let users own it
    ]
```

Alternatively, you can use a module-level variable:

```python
create_only_files = [
    "src/awesome_tool/__init__.py",
    "src/awesome_tool/py.typed",
    "src/awesome_tool/main.py",
    "tests/__init__.py",
    "tests/test_main.py",
]
```

### What happens

**First run** (new project):

```bash
$ repolish apply
```

- Creates entire package structure: `src/awesome_tool/`, `tests/`, etc.
- Creates `pyproject.toml`, `.github/workflows/ci.yml`
- User now has a complete, working package scaffold

**Later runs** (after user develops the package):

```bash
$ repolish apply
```

- **Skips** `src/awesome_tool/__init__.py` (user has added exports)
- **Skips** `src/awesome_tool/main.py` (user has implemented features)
- **Skips** `tests/test_main.py` (user has written tests)
- **Updates** `pyproject.toml` (latest dependencies, build config)
- **Updates** `.github/workflows/ci.yml` (latest CI improvements)

This gives you the best of both worlds: automated tooling/config updates via
repolish while keeping your actual code untouched

### Key behaviors

- **First run**: Files are created normally from the template
- **Subsequent runs**: Files are skipped if they exist, preserving user changes
- **Check mode**: Reports `MISSING` for create-only files that don't exist yet,
  but won't report diffs for files that exist (even if content differs)
- **Multiple providers**: create_only_files from multiple providers are merged
  (additive); later providers can add more create-only files
- **Works with file_mappings**: A file can be both in `file_mappings` (for
  conditional copying/renaming) and `create_only_files` (for preservation)
- **Conflicts with delete_files**: If a file is in both `create_only_files` and
  `delete_files`, the delete wins (file will be deleted)

### Use cases

This feature is ideal for:

- **Initial package scaffolding**: Create the package directory structure,
  `__init__.py` files, and starter modules for a new project, but leave them
  alone once the user starts developing
- **Example/template modules**: Provide example code (`main.py`,
  `test_example.py`) that users can modify or replace without repolish
  overwriting their work
- **Project-specific configs**: Files like `.gitignore`, `README.md`, or
  `.editorconfig` that should be created initially but are meant to be
  customized per-project
- **Type markers and metadata**: Files like `py.typed` that are needed for the
  package structure but never need updating
- **Separation of concerns**: Keep repolish managing your tooling/CI/build
  configs (always updated) while preserving your actual source code (created
  once, then hands-off)

The key insight: use create-only files for anything that serves as a **starting
point** rather than a **continuously synced template**. This lets you scaffold
new projects quickly while still getting the benefits of repolish for keeping
your tooling configuration up to date.

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

## Regex anchors and capture groups

Regex anchors let you specify exactly what to preserve from a local file. Two
important behaviors to know:

- Capture group preference: If your regex includes a capturing group
  (parentheses), Repolish will prefer the first capture group (group 1) as the
  block to insert into the template. If there are no capture groups, Repolish
  falls back to the entire match (group 0).
- Safeguard trimming: As a conservative safeguard Repolish trims captured blocks
  to a contiguous region based on indentation so that incidental following
  sections are not accidentally pulled into the template. However, the canonical
  way to express intent is an explicit capture group — authors should prefer to
  capture exactly what they mean.

Implementation note

- Repolish computes the absolute span of the selected capture (group 1 when
  present, otherwise the full match) inside the template and trims that slice
  using an indentation-aware heuristic before replacing it with the trimmed
  content extracted from the local file. Also note that the
  `## repolish-regex[...]` declaration line is removed from the template prior
  to matching and replacement. This avoids accidentally removing unrelated
  template sections when patterns include surrounding context.

Example

Template (excerpt):

```toml
cat1:
  - line1
  - line2
  ## repolish-regex[cat1-filter]: (^\s*# cat1-filter-additional-paths.*\n(?:\s+.*\n)*)
  # cat1-filter-additional-paths

cat2:
  - from-template
  ## repolish-regex[cat2-filter]: (^\s*# cat2-filter-additional-paths.*\n(?:\s+.*\n)*)
  # cat2-filter-additional-paths

cat3:
  - cat3-line
  ## repolish-regex[cat3-filter]: (^\s*# cat3-filter-additional-paths.*\n(?:\s+.*\n)*)
  # cat3-filter-additional-paths
```

Local file (excerpt):

```toml
cat1:
  - line1
  - line2
  # cat1-filter-additional-paths
  - extra

cat3:
  - cat3-line
  # cat3-filter-additional-paths
```

Result after preprocessing:

```toml
cat1:
  - line1
  - line2
  # cat1-filter-additional-paths
  - extra

cat2:
  - from-template
  # cat2-filter-additional-paths

cat3:
  - cat3-line
  # cat3-filter-additional-paths
```

When your regex is too greedy, tighten it or add explicit parentheses around the
intended capture so Repolish can reliably hydrate the template without importing
unrelated content.

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
