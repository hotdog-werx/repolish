# Configuration file schema

This document describes the keys recognized by `repolish.yaml` at load time. The
YAML file is parsed into a Pydantic model called `RepolishConfigFile` in
`repolish.config.models.project`. The schema below corresponds directly to that
class. You don't need to read or write the model yourself; it is shown here to
make the behaviour explicit and to document a couple of subtle features.

## Top‑level keys

Most keys are optional and will be defaulted, but **`providers` is required** –
Repolish cannot run without at least one provider configured.

- **`providers`** _(mapping of str to `ProviderConfig`)_ – the core of the
  configuration. Each entry describes one provider and its resource linking
  options (see below).

- **`providers_order`** _(list of strings)_ – an explicit ordering for
  processing providers. If omitted, YAML key order is used instead.

- **`template_overrides`** _(mapping of str to str)_ – allows you to pin a given
  output path to a specific provider, regardless of ordering. Keys are glob-like
  paths, values must name a provider defined elsewhere in the configuration. A
  validator ensures that all referenced providers actually exist.

## Providers subsection

The `providers` key is a dictionary whose keys are **aliases** – short names
used by configuration and in logged events. The value for each alias is a
`ProviderConfig` model that currently looks like::

```python
class ProviderConfig(BaseModel):
    cli: str | None = None
    directory: Path | None = None
    symlinks: list[Symlink] | None = None
```

Each provider entry must specify exactly one of `cli` or `directory`. The two
fields work as follows:

- **`cli`** – a shell command (string) that will be executed by `repolish-link`.
  The command must write a `.provider-info.json` file under the
  `.repolish/<alias>` directory; this JSON describes the template directory and
  any default symlinks. Libraries that ship a link CLI (e.g., `codeguide-link`)
  follow this pattern. The CLI is invoked once per provider when you run
  `repolish-link`; failure of one provider does not prevent the others from
  running.

- **`directory`** – a path pointing at the provider’s own resource directory.
  this directory must contain a `repolish.py` module or a `repolish/` template
  subfolder (the loader uses the presence of either to recognize the provider).
  the path is resolved relative to the configuration file's directory and is
  treated as the canonical source of templates when the corresponding provider
  has no CLI.

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

Each provider may also optionally supply a `symlinks` list. Entries are objects
with `source` and `target` keys; the source path is interpreted relative to the
provider's own resource directory, and the target is relative to the root of the
project. If the list is omitted, the provider’s defaults are used; an empty list
disables all symlinks.

## Notes on schema evolution

The `RepolishConfigFile` model intentionally mirrors the YAML and exists as an
intermediate representation. When the configuration is resolved (via
`repolish.config.resolve_config`) it becomes a
:class:`~repolish.config.models.project.RepolishConfig` instance, which contains
fully‑resolved absolute paths and provider metadata loaded from the
`.provider-info.json` files created by the link step.
