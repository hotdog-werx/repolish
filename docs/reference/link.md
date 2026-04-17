# repolish link

Link provider resources into the project.

```
repolish link [OPTIONS]
```

## Options

| Option                     | Default         | Description                                   |
| -------------------------- | --------------- | --------------------------------------------- |
| `--config PATH`, `-c PATH` | `repolish.yaml` | Path to the repolish YAML configuration file. |

## What it does

`repolish link` runs the registration pass for every provider in
`repolish.yaml`, always using `force=True` so each provider is re-registered
unconditionally regardless of what the cache contains.

For providers that declare a `cli` entry, the CLI is called in two steps:

1. `<cli> --info` - reads the JSON written to stdout and caches it as the
   provider's registration.
2. `<cli>` (without flags) - performs the actual linking (e.g. symlinking
   package resources into `.repolish/<name>/`).

For providers that only have `provider_root` set, the static paths from the YAML
are registered directly without calling any CLI.

After `repolish link` succeeds, subsequent `repolish apply` calls use the cached
registration and skip the CLI entirely on the fast path.

## When to run it

- After installing or upgrading a provider package.
- After a clean checkout where `.repolish/_/` does not exist yet.
- Whenever a provider's resources have moved on disk.

You do not need to run `repolish link` before every `repolish apply`. The
`apply` command will re-register automatically when a cached path is missing or
stale.
