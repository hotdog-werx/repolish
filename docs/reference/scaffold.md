# repolish scaffold

Scaffold a new repolish provider package.

```
repolish scaffold [OPTIONS] DIRECTORY
```

## Arguments

| Argument    | Description                                                                             |
| ----------- | --------------------------------------------------------------------------------------- |
| `DIRECTORY` | Destination directory. Created if it does not exist. Use `.` for the current directory. |

## Options

| Option                      | Required           | Default                     | Description                                                                                                                                                                 |
| --------------------------- | ------------------ | --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--package NAME`, `-p NAME` | with `--local`: no | -                           | Python package name. Use simple names for flat packages (e.g. `devkit_workspace`) or dot-notation for namespace packages (e.g. `devkit.workspace`).                         |
| `--prefix PREFIX`           | no                 | last segment of `--package` | Class-name prefix for generated provider classes (e.g. `Devkit` produces `DevkitProvider`, `DevkitContext`). With `--local` the alias, camel-cased, is the default.         |
| `--monorepo`                | no                 | off                         | Generate the full monorepo layout with `RootModeHandler`, `MemberModeHandler`, and `StandaloneModeHandler` classes. By default a simpler single-file provider is generated. |
| `--local`                   | no                 | off                         | Generate an in-repo local provider instead of an installable package. No `--package` needed; cannot be combined with `--monorepo`.                                          |

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

With `--local` the command generates an in-repo provider — a templates directory
that lives inside your project, not an installable package:

```
DIRECTORY/
  templates/
    repolish.py                    # Provider class entry point
    repolish/some-template.md.jinja  # sample template
```

Class names are derived from the directory name (`local_provider` produces
`LocalProvider` / `LocalProviderContext`); the alias used in `repolish.yaml` is
the directory name with dashes normalised to underscores, and the connect
snippet is printed on completion:

```yaml
providers:
  local_provider:
    provider_root: local_provider/templates
```

Local providers are meant to be quick: they ship templates under `repolish/` and
can define insertion functions for use throughout the project, without a CLI,
packaging, or publishing. See
[Local Providers](../project-controls/local-providers.md) for the full
mechanism.

## Examples

```bash
# Simple provider in a new directory
repolish scaffold ./my-provider --package my_provider

# Namespace package
repolish scaffold ./devkit-workspace --package devkit.workspace

# Monorepo-aware provider with custom class prefix
repolish scaffold ./devkit-workspace --package devkit.workspace --prefix Workspace --monorepo
```
