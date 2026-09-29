# repolish scaffold

Scaffold a new repolish provider package.

```
repolish scaffold [OPTIONS] DIRECTORY
```

## Arguments

| Argument    | Description                                                                                                                                         |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DIRECTORY` | Destination directory. Created if it does not exist. Defaults to `internal/` with `--local`; required otherwise. Use `.` for the current directory. |

## Options

| Option                      | Required           | Default                     | Description                                                                                                                                                                                                                   |
| --------------------------- | ------------------ | --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--package NAME`, `-p NAME` | with `--local`: no | -                           | Python package name. Use simple names for flat packages (e.g. `devkit_workspace`) or dot-notation for namespace packages (e.g. `devkit.workspace`).                                                                           |
| `--prefix PREFIX`           | no                 | last segment of `--package` | Class-name prefix for generated provider classes (e.g. `Devkit` produces `DevkitProvider`, `DevkitContext`). With `--local` the alias, camel-cased, is the default.                                                           |
| `--monorepo`                | no                 | off                         | Generate the full monorepo layout with `RootModeHandler`, `MemberModeHandler`, and `StandaloneModeHandler` classes. By default a simpler single-file provider is generated.                                                   |
| `--local`                   | no                 | off                         | Generate an in-repo local provider at `internal/` (see below) instead of an installable package. No `--package` needed; cannot be combined with `--monorepo`.                                                                 |
| `--flat`                    | no                 | off                         | With `--local`, scaffold the flat tier instead of the default installable one: a single self-contained `templates/repolish.py` and a `cli.py` beside it, with no `pyproject.toml` and nothing to install. Requires `--local`. |

## What it does

`repolish scaffold` generates the boilerplate for a new provider package inside
`DIRECTORY`:

```
DIRECTORY/
  pyproject.toml
  README.md
  repolish.yaml          # example config pointing at this provider
  <package>/
    repolish.py          # Provider class and context model
    repolish/            # empty template tree (add .jinja files here)
    linker.py            # resource_linker_cli() entry point
```

Existing files are never overwritten. If a file already exists at a target path
it is skipped and reported in the summary.

## Simple vs monorepo layout

Without `--monorepo` the generated `repolish.py` contains a single
`Provider[Ctx, BaseInputs]` subclass:

```python
class MyProvider(Provider[MyCtx, BaseInputs]):
    def create_context(self) -> MyCtx:
        return MyCtx()
```

With `--monorepo` it also generates `RootModeHandler`, `MemberModeHandler`, and
`StandaloneModeHandler` classes attached via `root_mode`, `member_mode`, and
`standalone_mode` - each with stub implementations of `provide_inputs()`,
`finalize_context()`, and `create_file_mappings()` for the relevant mode.

## Local provider layout

With `--local` the command generates an in-repo provider: a templates directory
that lives inside your project and is never published. **No `--package` is
needed**: the package name is derived from the provider class. **No `DIRECTORY`
is needed either**: by convention the provider lives at `internal/`, sibling to
`src/`. Its code only maintains this repo and is never shipped, so it does not
belong under the project source tree.

Copy-paste example. This creates `internal/` with a provider class named
`LocalProvider`:

```bash
repolish scaffold --local
```

```
internal/
  pyproject.toml
  local_provider/            # the real code: an editable-installed package
    __init__.py               # __version__
    provider.py               # LocalProvider / LocalProviderContext
    cli.py                    # fast-lane CLI: imports the class from the package
  templates/
    repolish.py               # entry point: a shim re-exporting from local_provider
    repolish/
      some-template.md.jinja  # sample template (rendered to some-template.md)
```

The provider is aliased `local` and named `LocalProvider` /
`LocalProviderContext` no matter which directory you pass (an explicit
`DIRECTORY` only relocates it). Class names can be overridden with `--prefix`.
On completion the command prints the snippet to paste into `repolish.yaml`:

```yaml
providers:
  local:
    provider_root: internal/templates
```

Editable-install `internal/` into the environment that runs repolish (e.g.
`-e ./internal` in its requirements). Sibling imports work because the code is
loaded as an installed package, not by file path. The pyproject declares the
`local-cli` console script (`local_provider.cli:main`), so lanes run as
`local-cli <lane>` from anywhere once installed.

Then `repolish link` and `repolish apply` work as usual. Local providers are
meant to be quick: they ship templates under `repolish/` and can define
insertion functions for use throughout the project, without publishing. See
[Fast Lanes](../provider-development/fast-lanes/cli.md#local-providers) for the
CLI wiring and [Local Providers](../project-controls/local-providers.md) for the
full mechanism.

### Flat tier (`--flat`)

The flat tier is the zero-install variant, for when the venv that runs repolish
is not yours to touch: no `pyproject.toml`, nothing to install.

```bash
repolish scaffold --local --flat
```

```
internal/
  cli.py                            # fast-lane CLI wiring (provider_cli)
  templates/
    repolish.py                      # the whole implementation: LocalProvider
    repolish/
      some-template.md.jinja         # sample template (rendered to some-template.md)
```

`templates/repolish.py` is the whole implementation. Repolish loads it directly
by file path, so it **cannot import sibling modules** (they are not on
`sys.path`); move to the default tier when the provider wants multiple modules.
The wiring (`provider_root: internal/templates`) is identical for both tiers, so
the upgrade is additive. The CLI sits beside `templates/`, not inside it:
running a file as a script puts its directory first on `sys.path`, where the
provider's `repolish.py` would shadow the `repolish` package. Run it from the
project root:

```bash
python internal/cli.py <lane>
```

## Examples

```bash
# Simple provider in a new directory
repolish scaffold ./my-provider --package my_provider

# Namespace package
repolish scaffold ./devkit-workspace --package devkit.workspace

# Monorepo-aware provider with custom class prefix
repolish scaffold ./devkit-workspace --package devkit.workspace --prefix Workspace --monorepo

# In-repo local provider at internal/ (nothing else needed; class becomes LocalProvider)
repolish scaffold --local

# Same, but flat: single file, nothing to editable-install
repolish scaffold --local --flat
```
