# repolish list-insertions

List the insertion functions the configured providers offer, and which files
they may fill. This is the orientation command for the insertion feature: run it
to see what is available before writing marker blocks into your files.

```
repolish list-insertions [OPTIONS]
```

## Arguments

The table below is generated from the list-insertions parameter model in the CLI
code, so it cannot drift.

<!-- repolish:on:options cli-options list-insertions -->

| Argument                       | Default         | Description                                  |
| ------------------------------ | --------------- | -------------------------------------------- |
| `--config PATH`, `-c PATH`     | `repolish.yaml` | Path to the repolish YAML configuration file |
| `--provider VALUE`, `-p VALUE` | `None`          | Filter by provider alias                     |
| `--function VALUE`, `-f VALUE` | `None`          | Filter by insertion function name            |

<!-- repolish:off:options -->

## What it does

For every provider that declares insertion functions, the command prints the
function names with their docstring summaries and the files the provider is
allowed to fill. `--provider` and `--function` narrow the listing.

```
available insertion functions (1 providers, 6 functions)
├── files gate developer markers; template zones may call any listed function
└── local (6 functions)
    ├── cli-commands - Command index for the CLI landing page, from the entry
    │   functions.
    │   └── files (repolish:on markers): README.md, docs/...
    ├── cli-options - Argument table; `command` picks the cyclopts parameter
    ...
```

The listed files are the provider's allowlist: marker blocks anywhere else are
not filled by that provider. See [Insertions](../markers/insertions.md) for the
marker grammar and [Insertion Zones](../markers/insert-zones.md) for zones.

## CI usage

Not a CI command: this is a local development aid. The CI-relevant neighbor is
the drift check, which validates insertion blocks as part of the run:

```bash
repolish apply --check
```

A block whose filled body no longer matches its function's output is reported as
drift.
