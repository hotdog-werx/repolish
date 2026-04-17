# Configuration file schema

This document describes the keys recognized by `repolish.yaml` at load time. The
YAML file is parsed into a Pydantic model called `RepolishConfigFile` in
`repolish.config.models.project`. The schema below corresponds directly to that
class. You don't need to read or write the model yourself; it is shown here to
make the behaviour explicit and to document a couple of subtle features.

## Top‑level keys

Most keys are optional and will be defaulted, but **`providers` is required** -
Repolish cannot run without at least one provider configured.

- **`providers`** _(mapping of str to `ProviderConfig`)_ - the core of the
  configuration. Each entry describes one provider and its resource linking
  options (see below).

- **`providers_order`** _(list of strings)_ - an explicit ordering for
  processing providers. If omitted, YAML key order is used instead.

- **`template_overrides`** _(mapping of str to str)_ - allows you to pin a given
  output path to a specific provider, regardless of ordering. Keys are glob-like
  paths, values must name a provider defined elsewhere in the configuration. A
  validator ensures that all referenced providers actually exist.

- **`delete_files`** _(list of strings)_ - POSIX-style paths that repolish
  should delete from the project after generation. A leading `!` negates a path,
  cancelling a delete that a provider scheduled:

  ```yaml
  delete_files:
    - legacy/old-config.ini # delete this
    - '!legacy/keep-this.ini' # cancel a provider-scheduled delete
  ```

  Negation is evaluated in list order. This is useful when a provider's
  `FileMode.DELETE` mapping removes a file that your project still needs.

- **`post_process`** _(list of strings)_ - shell commands to run after
  rendering, inside the `.repolish/_/render/` directory. This is where
  formatters live — running `ruff format .` or `prettier --write .` here ensures
  the diff and apply steps always operate on correctly formatted output.
  Commands run in order; if any exits non-zero repolish stops immediately.

  ```yaml
  post_process:
    - ruff format .
    - ruff check --fix .
  ```

- **`paused_files`** _(list of strings)_ - POSIX-style file paths that repolish
  should temporarily ignore. Paused files are excluded from both `--check`
  comparison and `apply` writes. Use this to opt out of provider management for
  specific files while a provider is being fixed or updated. See
  [Pause a File](../project-controls/pause.md) for details.

  ```yaml
  paused_files:
    - .github/workflows/ci.yml # provider#42 pending
  ```

- **`workspace`** _(optional mapping)_ - enables workspace (monorepo) mode. When
  present, repolish runs a session for the root and one for each discovered
  member. Accepts one optional sub-key:

  - **`members`** _(list of strings, optional)_ - repo-relative paths to
    workspace members. When set, overrides auto-detection from
    `[tool.uv.workspace]` in the root `pyproject.toml`. Omit to let repolish
    discover members automatically.

  ```yaml
  workspace:
    members:
      - packages/core
      - packages/utils
  ```

## Providers subsection

The `providers` key is a dictionary whose keys are **aliases** - short names
used by configuration and in logged events. The value for each alias is a
`ProviderConfig` model that currently looks like::

```python
class ProviderConfig(BaseModel):
    cli: str | None = None
    provider_root: Path | None = None
    resources_dir: Path | None = None
    symlinks: list[Symlink] | None = None
    context: dict[str, Any] | None = None
    context_overrides: dict[str, Any] = {}
    anchors: dict[str, str] | None = None
```

Each provider entry must specify at least one of `cli` or `provider_root`; they
may also be combined. See the [Provider configuration](providers.md) guide for
the full resolution rules and CLI protocol.

- **`cli`** - a shell command (string) that will be executed by `repolish link`.
  The command must write a `.provider-info.json` file under the
  `.repolish/<alias>` directory; this JSON describes the template directory and
  any default symlinks. Libraries that ship a link CLI (e.g., `codeguide-link`)
  follow this pattern. The CLI is invoked once per provider when you run
  `repolish link`; failure of one provider does not prevent the others from
  running.

- **`provider_root`** - path to the root of the provider package (the directory
  that contains `repolish.py` and the `repolish/` template subfolder). The path
  is resolved relative to the configuration file’s directory. Use this for
  providers that are checked in locally rather than distributed as a package.

- **`resources_dir`** - optional path to the directory from which symlinks are
  created into the project. When omitted it defaults to `provider_root`. Specify
  this when the symlink root lives inside a subdirectory of `provider_root`.

- **`context`** - optional mapping merged into this provider's context after
  `create_context()` runs. Each top-level key replaces the provider's value
  wholesale. See [Override Context](../project-controls/context-overrides.md).

- **`context_overrides`** - dot-notation overrides applied after
  `finalize_context()`. Allows surgical patching of nested context fields
  without repeating the entire object. See
  [Override Context](../project-controls/context-overrides.md).

- **`anchors`** - optional mapping of anchor name to replacement string. Merged
  on top of whatever `create_anchors()` returns for this provider; config-level
  values take precedence. Overrides are scoped to the provider they appear under
  — one provider's `anchors` cannot affect another provider's anchors. Providers
  should document which anchor keys they support. See
  [Block anchors](../project-controls/anchors.md).

Shorthand notation is supported in the YAML. Instead of writing::

```yaml
providers:
  base:
    cli: codeguide-link
```

you may simply write::

```yaml
providers:
  base: codeguide-link
```

The model validator normalizes this into a `ProviderConfig` with the string
assigned to `cli`.

### Symlinks

Each provider may declare default symlinks in its `create_default_symlinks()`
method. The `symlinks` key in `repolish.yaml` lets you override those defaults
per-project:

- **Omit `symlinks`** - use whatever the provider declares as defaults.
- **`symlinks: []`** - disable all symlinks for this provider.
- **Explicit list** - use exactly this list; the provider's defaults are
  ignored.

```yaml
providers:
  mylib:
    cli: mylib-link
    symlinks:
      - source: configs/.editorconfig
        target: .editorconfig
      - source: configs/.gitignore
        target: .gitignore
```

Each entry has a `source` path (relative to the provider's `resources_dir`) and
a `target` path (relative to the project root). This is the mechanism for adding
symlinks the provider doesn't ship by default, or for trimming ones you don't
want.

## Notes on schema evolution

The `RepolishConfigFile` model intentionally mirrors the YAML and exists as an
intermediate representation. When the configuration is resolved (via
`repolish.config.resolve_config`) it becomes a
:class:`~repolish.config.models.project.RepolishConfig` instance, which contains
fully‑resolved absolute paths and provider metadata loaded from the
`.provider-info.json` files created by the link step.
