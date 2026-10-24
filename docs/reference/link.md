# repolish link

Link provider resources into the project.

```
repolish link [OPTIONS] [ALIAS] [MODULE]
```

With no arguments every provider in `repolish.yaml` is linked. With `ALIAS` only
that provider is linked. With `ALIAS` and `MODULE` the given module is linked
under the alias as a one-off that does not require a config entry.

## Arguments

<!-- repolish:on:options cli-options link -->

| Argument                   | Default         | Description                                                                                                                                             |
| -------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ALIAS`                    | `None`          | Link only the provider aliased ALIAS in repolish.yaml. With MODULE, instead links MODULE under ALIAS as a one-off that does not require a config entry. |
| `MODULE`                   | `None`          | Dotted module name for a one-off link under ALIAS (e.g. devkit.workspace). Requires ALIAS.                                                              |
| `--config PATH`, `-c PATH` | `repolish.yaml` | Path to the repolish YAML configuration file                                                                                                            |
| `--force`                  | `False`         | Force re-linking all providers even if already linked                                                                                                   |
| `--no-config`              | `False`         | Do not read the repolish YAML configuration. Requires an ALIAS and MODULE pair; with a config file present, its entry for ALIAS is explicitly ignored.  |
| `--register-only`          | `False`         | Register providers only: create the .repolish/ resource link and provider info, skip project-root symlinks and copies.                                  |

<!-- repolish:off:options -->

## What it does

`repolish link` runs the registration pass for every provider in
`repolish.yaml`. It is the refresh point for provider locations: unlike
`repolish apply` (which trusts a valid cache outright), `link` verifies that
each cached registration still points where the provider actually lives.

For providers that declare a `cli` entry, the CLI is called in two steps:

1. `<cli> --info` - reads the JSON written to stdout and compares it with the
   cached registration.
2. `<cli>` (without flags) - performs the actual linking (e.g. symlinking
   package resources into `.repolish/<name>/`). This step is **skipped** when
   the probe reports the same location as the cache and the `.repolish/<name>`
   link is still intact — the provider shows up as `(cached)` and only the
   single `--info` probe ran.

Because the probe reads the package's current location, a plain `repolish link`
detects dev ↔ release switches (e.g. swapping between an editable install and a
released wheel) without `--force`. Use `--force` to re-register all providers
unconditionally.

For providers that only have `provider_root` set, the cached paths are compared
against the paths implied by the YAML — a config edit re-registers the provider,
an unchanged config is a cache hit. No subprocess is involved.

After `repolish link` succeeds, subsequent `repolish apply` calls use the cached
registration and skip the CLI entirely on the fast path.

## Linking a single provider

`repolish link <alias>` links only the provider aliased `<alias>` in
`repolish.yaml`, running the same phases a full link runs for it: registration,
project-root symlinks, and copies. Every other provider is skipped before it is
consulted, so a CI job can bring in one provider's configuration without
installing the other provider packages.

An alias that no config declares is an error listing the valid aliases. In a
monorepo the alias links wherever it is declared: the root and members without
it are skipped, and the run fails only when no config declares it at all.

## One-off links

`repolish link <alias> <module>` links `<module>` under `<alias>` without a
config entry. This is for one-offs: CI jobs that need one provider's resources
in a repository that does not configure repolish for them.

- The alias must not exist in the config unless `--no-config` is also given.
  Silently shadowing a configured provider is never allowed.
- `--no-config` does not read the config file at all. The link uses the module
  name with `.` and `_` normalized to `-` (e.g. `devkit.workspace` links to
  `.repolish/devkit-workspace/`), and `paused_files` does not apply.
- Without `--no-config`, a present config contributes the project-level link
  settings (`module_links`, `paused_files`) even though the provider selection
  comes only from the command line.
- A one-off runs in the configuration directory: workspace members are not
  visited even when a workspace is detected.

The CI recipe for a repository without a repolish config:

```
repolish link <alias> <module> --no-config --register-only
```

Add `--register-only` when only the `.repolish/<name>/` resource link is needed;
drop it to also materialize the provider's project-root symlinks and copies.

## Registration only

`--register-only` stops after the registration phase: the `.repolish/<name>/`
resource link and the provider info files are written, and the resolve,
project-root symlink, and copy phases are skipped. This is the scope the
generated `<library>-link` CLIs had before `module:` registration replaced them;
those CLIs are removed in v2.

## When to run it

- After installing or upgrading a provider package.
- After a clean checkout where `.repolish/_/` does not exist yet.
- Whenever a provider's resources have moved on disk.

You do not need to run `repolish link` before every `repolish apply`. The
`apply` command will re-register automatically when a cached path is missing or
stale.
