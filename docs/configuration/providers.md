# Provider configuration

Each entry in the `providers` map describes one provider and how repolish should
locate its resources. Three fields control this:

```yaml
providers:
  mylib:
    cli: mylib-link # optional
    provider_root: ./mylib # optional
    resources_dir: ./mylib # optional, requires provider_root
```

At least one of `cli` or `provider_root` is required. The two may coexist - see
the resolution rules below.

---

## Fields

### `cli`

A shell command that repolish calls when you run `repolish link`. The command
must support a `--info` flag (see [CLI protocol](#cli-protocol) below).

When `repolish link` runs it:

1. Calls `<cli> --info` and reads the JSON written to stdout.
2. Caches that JSON internally so subsequent commands can resolve the provider
   without calling the CLI again.
3. Calls `<cli>` (without flags) to perform the actual linking.

Any CLI that implements this protocol works - it does not have to be a Python
package or use the repolish linker helpers.

### `provider_root`

Path to the directory that contains `repolish.py` and the `repolish/` template
tree. Resolved relative to the config file.

Use this for providers that are checked in locally, installed via npm, or
otherwise not distributed as a Python package with a built-in CLI linker.

### `resources_dir`

Root of the provider's resources inside the project (e.g. `.repolish/mylib/`).
This is typically the _parent_ of `provider_root` - it may also contain
additional folders such as `configs/`. Symlink `source` paths are resolved
relative to this directory. When omitted it falls back to `provider_root` (i.e.
no separate parent directory). Requires `provider_root` to be set.

---

## Resolution rules

When repolish resolves a provider it applies these rules in order:

1. **Cached registration found** - repolish has a cached registration for this
   alias from a previous `repolish link` run. The paths from that cache are
   used. If `provider_root` is also set in the YAML it is ignored and a
   `provider_root_ignored` warning is emitted.
2. **No cache, `cli` set** - repolish attempts to auto-link by running the CLI
   on the fly (same two-step call described above). If that succeeds the
   resulting info is used.
3. **No cache, `provider_root` set** - the static paths from the YAML are used
   directly; no CLI is called. This is the fallback for CLIs that do not
   implement `--info`.
4. **Neither** - the provider is skipped with a `provider_not_resolved` warning.

### Combining `cli` and `provider_root`

Setting both is intentional when the provider's CLI does not implement the
`--info` protocol. In that case:

- Run `repolish link` as normal - the CLI performs whatever linking it does.
- repolish uses `provider_root` / `resources_dir` to learn where things landed,
  enabling template rendering and symlink management without requiring the CLI
  to produce a provider-info file.

```yaml
providers:
  third-party:
    cli: third-party-link # does linking, but no --info support
    provider_root: .repolish/third-party
    resources_dir: .repolish/third-party
```

---

## Provider registration

Both `repolish link` and `repolish apply` run a **registration pass** before
doing any real work. The goal is to guarantee that every provider is fully
registered before templates are rendered or files are written.

!!! note "`.repolish/_` is reserved"

    The `.repolish/_` directory is repolish's internal working space. Its
    contents and layout can change between versions - treat it as an
    implementation detail. It is intentionally visible so you can inspect what
    repolish knows about each provider, but nothing in there should be read or
    written by consumers directly.

### How the registration pass works

For each alias (in `providers_order` order, or config key order if not set):

1. **Load the cached registration** - if a cached registration for the alias
   exists, check that the paths it records still exist on disk.
2. **Cache hit** - paths are valid and `force` is not set → provider is ready,
   nothing else happens. This is the normal fast path for `repolish apply`.
3. **Cache miss or stale** - the cached paths are gone (e.g. after a clean
   checkout, a `pip install -e`, or a directory rename). repolish attempts
   re-registration using the same rules as `repolish link`:
   - If `cli` is set, it is called first.
   - If the CLI fails and `provider_root` is also set, the static paths are used
     as a fallback.
   - If only `provider_root` is set, the static paths are used directly.
4. **Failure** - registration could not complete (CLI error, missing directory).
   The alias is recorded as failed, a warning is logged, and the provider is
   absent from the run. Other providers are unaffected.

`repolish link` always uses `force=True`, so it re-registers every provider
unconditionally regardless of what the cache contains.

### Behaviour when a provider fails

By default a failed provider emits a warning and is skipped - the command still
exits 0 so the rest of the run completes. This keeps local development workflows
smooth when a provider is temporarily unavailable.

Use `--strict` with `repolish apply` to change this to a hard error (exit 1).
This is recommended for CI pipelines where a missing provider means the output
is incomplete:

```yaml
# .github/workflows/ci.yaml
- run: repolish apply --strict
```

### Aliases missing from the providers map

If `providers_order` lists an alias that has no entry in the `providers` map, a
`provider_not_in_config` warning is logged and the alias is silently skipped.
This is intentional - `providers_order` may reference providers that have been
temporarily removed without breaking the run.

---

## CLI protocol

Providers that want full repolish integration should implement a CLI that
supports a `--info` flag. When called with `--info` the command must print a
JSON object to stdout and exit 0. The object must conform to the `ProviderInfo`
schema:

```json
{
  "resources_dir": "/abs/path/to/.repolish/myprovider",
  "provider_root": "/abs/path/to/.repolish/myprovider/templates",
  "site_package_dir": "/abs/path/to/site-packages/myprovider/resources",
  "package_name": "myprovider",
  "project_name": "my-provider",
  "symlinks": [
    { "source": "configs/.editorconfig", "target": ".editorconfig" }
  ]
}
```

Field reference:

| Field              | Required | Description                                                                                                                                                    |
| ------------------ | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `resources_dir`    | yes      | Absolute path to the directory where provider resources are linked into the project (e.g. `.repolish/myprovider/`).                                            |
| `provider_root`    | no       | Absolute path to the directory containing `repolish.py` and the `repolish/` template tree. Empty string or omit to mean the same directory as `resources_dir`. |
| `site_package_dir` | no       | Absolute path to the provider resources inside its installed package. Informational only.                                                                      |
| `package_name`     | no       | Python import name of the provider package (e.g. `my_provider`).                                                                                               |
| `project_name`     | no       | Distribution name of the provider package (e.g. `my-provider`).                                                                                                |
| `symlinks`         | no       | Default symlinks the provider wants created. Each entry has a `source` (relative to `resources_dir`) and a `target` (relative to project root).                |

When called **without** `--info` the CLI performs the actual linking (e.g.
symlinking the package resources into `.repolish/<name>/`).

### Using the built-in linker helper

If you are writing a Python provider package you can use `resource_linker_cli()`
from `repolish.linker` to get a compliant CLI with zero boilerplate:

```python
# mypackage/linker.py
from repolish.linker import resource_linker_cli

main = resource_linker_cli()
```

Register the entry point in `pyproject.toml`:

```toml
[project.scripts]
mypackage-link = "mypackage.linker:main"
```

`resource_linker_cli()` auto-detects the package root, produces the `--info`
JSON, and handles the link step. See the `resource_linker` decorator for
advanced options (custom templates directory, default symlinks, etc.).
