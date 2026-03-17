# Template Files

This guide covers how to structure and write template files for Repolish.

## Template Directory Structure

Provider templates are organized under a `repolish/` directory within each
provider. This directory contains the project layout files that will be
processed and copied to your project:

```
my-provider/
├── repolish.py              # Provider factory (required)
└── repolish/                # Template directory (required)
    ├── README.md
    ├── pyproject.toml
    ├── src/
    │   └── __init__.py
    └── tests/
        └── test_example.py
```

All files under `repolish/` will be processed with Jinja2 templating and copied
to your project when you run `repolish`.

## Jinja Extension for Syntax Highlighting

Template files can optionally use a `.jinja` extension to enable proper syntax
highlighting in editors like VS Code. This is especially useful for
configuration files that contain Jinja template syntax:

```
repolish/
├── pyproject.toml.jinja     # TOML with Jinja highlighting
├── config.yaml.jinja        # YAML with Jinja highlighting
├── Dockerfile.jinja         # Dockerfile with Jinja highlighting
└── README.md                # Regular Markdown (no .jinja needed)
```

### How It Works

When Repolish processes your templates, it automatically strips the `.jinja`
extension from filenames before copying them to your project:

- `pyproject.toml.jinja` → `pyproject.toml`
- `config.yaml.jinja` → `config.yaml`
- `Dockerfile.jinja` → `Dockerfile`

This means you get the benefit of syntax highlighting in your editor while
editing templates, but the generated files have normal extensions.

### Editor Configuration

Many VS Code extensions recognize the `.jinja` extension and provide proper
syntax highlighting. For example:

- **YAML files**: `config.yaml.jinja` gets both YAML and Jinja highlighting
- **TOML files**: `pyproject.toml.jinja` gets TOML and Jinja highlighting
- **HTML files**: `template.html.jinja` gets HTML and Jinja highlighting

Common extensions that support this pattern:

- [Better Jinja](https://marketplace.visualstudio.com/items?itemName=samuelcolvin.jinjahtml)
- [Jinja](https://marketplace.visualstudio.com/items?itemName=wholroyd.jinja)

### Special Case: Actual Jinja Templates

If you need to generate actual `.jinja` files (files that will themselves be
Jinja templates), use a double `.jinja.jinja` extension:

```
repolish/
└── my-template.jinja.jinja  # Generates: my-template.jinja
```

The rule is simple: if a template filename ends in `.jinja`, that extension will
be removed in the generated output.

## Template Syntax

Templates use Jinja2 syntax to reference context variables:

```jinja
# {{ cookiecutter.package_name }}

Version: {{ cookiecutter.version }}
Author: {{ cookiecutter.author }}
```

See the [Preprocessors guide](preprocessors.md) for information about advanced
features like anchors, create-only blocks, and conditional content.

## Jinja rendering (cookiecutter removed)

All template rendering now uses Jinja2 exclusively; the legacy Cookiecutter
wrapper and its configuration flag have been dropped. Projects no longer need to
opt in, and the `repolish.yaml` schema no longer contains a `no_cookiecutter`
setting.

The merged provider context is available both as top‑level variables and, for
backwards compatibility, under the `cookiecutter` namespace. Thus existing
templates continue to work while you gradually remove the `cookiecutter.`
prefix.

Why we switched to Jinja:

- binds more naturally to Python data types and avoids Cookiecutter's CLI option
  quirks (arrays, prompts, etc.).
- provides stricter validation via `StrictUndefined`, catching missing keys
  early in preview runs.
- allows features like tuple-valued `file_mappings` and per‑file extra context
  without special cases.

Migration is automatic for most users; simply remove any residual
`no_cookiecutter` settings and continue editing templates as before. The old
namespace remains available during transition.

## Best Practices

1. **Use `.jinja` for syntax highlighting**: Add `.jinja` to files with
   significant Jinja templating to improve editor experience
2. **Keep it optional**: Files without Jinja syntax don't need the extension
3. **Consistent naming**: Use the same pattern across your templates for clarity
4. **Test both ways**: Verify your templates work with and without the extension
   since the generated output is identical

## Conditional files (file mappings)

Template authors can provide multiple alternative files and conditionally choose
which one to copy based on context. This keeps filenames clean without
`{% if %}` clutter in paths.

### How it works

Every file under a provider's `repolish/` directory is **auto-staged** to the
project at its natural path. `create_file_mappings()` maps a _destination_ path
(the key) to a _source_ template (the value). When a source is listed in
`file_mappings` it becomes a staging intermediate — it is rendered and written
at the mapped destination, never at its own natural path.

By convention, source-only templates are named with a `_repolish.` prefix so
they are easy to identify and so a typo (forgetting to map them) doesn't produce
a garbage file in the project. The prefix has no runtime special meaning; the
exclusion from auto-staged output applies to any file that appears as a mapping
source, regardless of name.

The `file_mappings` return value is a dict where:

- **Keys** are destination paths in the final project (must be unique)
- **Values** are source paths in the template, a `TemplateMapping`, or `None` to
  skip

### Example

Template directory structure:

```
templates/my-template/
├── repolish.py
└── repolish/
    ├── README.md                          # auto-staged → project/README.md
    ├── _repolish.poetry-pyproject.toml    # mapping source only (never auto-staged)
    ├── _repolish.setup-pyproject.toml     # mapping source only
    └── .github/
        └── workflows/
            ├── _repolish.github-ci.yml    # mapping source only (nested)
            └── _repolish.gitlab-ci.yml    # mapping source only (nested)
```

`repolish.py`:

```python
def create_context():
    return {
        "use_github_actions": True,
        "use_poetry": False,
    }

def create_file_mappings():
    ctx = create_context()
    return {
        ".github/workflows/ci.yml": (
            ".github/workflows/_repolish.github-ci.yml"
            if ctx["use_github_actions"]
            else ".github/workflows/_repolish.gitlab-ci.yml"
        ),
        "pyproject.toml": (
            "_repolish.poetry-pyproject.toml" if ctx["use_poetry"]
            else "_repolish.setup-pyproject.toml"
        ),
        # None means skip — don't copy this file
        ".pre-commit-config.yaml": None,
    }
```

### Auto-staging vs. explicit mappings

Every file under a provider's `repolish/` directory is **auto-staged** — copied
to the project at its natural path automatically, without any `file_mappings`
entry. `create_file_mappings()` is only needed when you want to redirect a
source template to a _different_ destination path or pick between alternatives
at runtime.

When a file path appears as a **value** in `file_mappings` (i.e. as a source),
the loader registers it as a staging intermediate: the file is rendered with the
provider's context and written to a temporary location, then applied at the
mapped destination. It is **not** written to its own natural path in the
project.

The `_repolish.` prefix is a convention that makes this intent explicit — a file
named `_repolish.config-a.yml` will never end up in the project at
`_repolish.config-a.yml` because the loader treats it as a pure staging source.
But the prefix is not required; any file can serve as a mapping source, and it
will be excluded from the auto-staged output regardless of its name.

```
repolish/
├── config.yml                  # auto-staged → written to project as config.yml
├── _repolish.config-a.yml      # NOT auto-staged → only used when mapped
└── _repolish.config-b.yml      # NOT auto-staged → only used when mapped
```

```python
def create_file_mappings(ctx):
    return {
        'config.yml': (
            '_repolish.config-a.yml' if ctx.variant == 'a'
            else '_repolish.config-b.yml'
        ),
    }
```

Here `config.yml` is both auto-staged (it exists under `repolish/`) **and** the
destination of a mapping. The mapping wins: the auto-staged copy is replaced by
whichever source the mapping resolves to.

### `{{ _provider }}` in mapped sources

Mapped source templates have full access to the provider's context, including
`{{ _provider.alias }}`, `{{ _provider.version }}`, and
`{{ _provider.project_name }}` — the same variables available in auto-staged
templates.

### Key behaviours

- **Auto-staged files** (all files under `repolish/`) are copied to the project
  at their natural path unless they are mapping sources or suppressed with
  `None`.
- **Mapping sources** are staging intermediates: rendered once and applied at
  the mapped destination, never written at their own path.
- **`_repolish.` prefix** is a naming convention signalling "this file is a
  staging-only source". It has no special runtime effect; it simply prevents
  accidental auto-staging at an ugly path.
- **Destinations are unique**: you cannot map multiple sources to the same
  destination within a single provider.
- **None values are skipped**: returning `None` means "don't copy this file".
- **Multiple providers**: file mappings from multiple providers are merged;
  later providers override earlier ones for the same destination.

`TemplateMapping` entries allow per-file extra context and typed rendering:

```python
from pydantic import BaseModel
from repolish import TemplateMapping

class PkgCtx(BaseModel):
    extra_key: str

def create_file_mappings(ctx):
    return {
        'pyproject.toml': TemplateMapping(
            '_repolish.setup-pyproject.toml',
            PkgCtx(extra_key='value'),
        ),
    }
```

## Create-only files

Files listed in `create_only_files` are created when they do not exist in the
project and skipped on all subsequent runs. This is useful for initial
scaffolding — source files, example tests, README stubs — that should be created
once and then owned by the developer.

### How it works

- **Present**: file is skipped (user modifications are preserved)
- **Absent**: file is created normally from the template
- **Check mode**: reports `MISSING` for absent create-only files but does not
  report diffs for files that already exist, even if content differs

### Example

`repolish.py`:

```python
def create_context():
    return {"package_name": "awesome_tool"}

def create_create_only_files():
    pkg = create_context()["package_name"]
    return [
        f"src/{pkg}/__init__.py",
        f"src/{pkg}/py.typed",
        f"src/{pkg}/main.py",
        "tests/__init__.py",
        "tests/test_main.py",
        "README.md",
    ]
```

Alternatively, use a module-level variable:

```python
create_only_files = [
    "src/awesome_tool/__init__.py",
    "src/awesome_tool/py.typed",
]
```

### What happens across runs

**First run** (new project):

```bash
repolish apply
```

Creates the full scaffold: `src/awesome_tool/`, `tests/`, etc., along with
`pyproject.toml` and CI configs.

**Later runs** (after the developer has written code):

```bash
repolish apply
```

- Skips `src/awesome_tool/__init__.py`, `tests/test_main.py`, etc. — user
  modifications are untouched.
- Updates `pyproject.toml`, `.github/workflows/ci.yml`, and other regular
  template files as usual.

### Key behaviours

- **Multiple providers**: `create_only_files` lists are merged additively.
- **Works with file_mappings**: a file can be both conditional and create-only.
- **Conflicts with delete_files**: if a file appears in both, the delete wins.
