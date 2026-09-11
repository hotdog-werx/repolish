# repolish link

Link provider resources into the project.

```
repolish link [OPTIONS]
```

## Options

| Option                     | Default         | Description                                                        |
| -------------------------- | --------------- | ------------------------------------------------------------------ |
| `--config PATH`, `-c PATH` | `repolish.yaml` | Path to the repolish YAML configuration file.                      |
| `--force`                  | `False`         | Force re-linking all providers even if already linked (slow path). |

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

## When to run it

- After installing or upgrading a provider package.
- After a clean checkout where `.repolish/_/` does not exist yet.
- Whenever a provider's resources have moved on disk.

You do not need to run `repolish link` before every `repolish apply`. The
`apply` command will re-register automatically when a cached path is missing or
stale.
