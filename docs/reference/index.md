# CLI

repolish is invoked as a single top-level command with subcommands for each
operation. The global `-v` flag is available to all subcommands.

```
repolish [OPTIONS] COMMAND [ARGS]...
```

## Global options

| Flag        | Description                                                                                         |
| ----------- | --------------------------------------------------------------------------------------------------- |
| `-v`        | Increase verbosity. Pass once for structured log output, twice (`-vv`) for detailed debug messages. |
| `--version` | Print the installed version and exit.                                                               |
| `--help`    | Show help and exit.                                                                                 |

## Commands

The table below is generated from the CLI entry functions in the code, so a
command registered on the app is missing from the docs only until it is added to
the renderer's registry, which a test enforces.

<!-- repolish:on:commands cli-commands -->

| Command                                 | Description                                                   |
| --------------------------------------- | ------------------------------------------------------------- |
| [`apply`](apply.md)                     | Apply templates to project.                                   |
| [`link`](link.md)                       | Link provider resources to the project.                       |
| [`lint`](lint.md)                       | Lint a provider's templates against its context model.        |
| [`list-insertions`](list-insertions.md) | List insertion functions available from configured providers. |
| [`preview`](preview.md)                 | Preview/test templates.                                       |
| [`scaffold`](scaffold.md)               | Scaffold a new repolish provider.                             |

<!-- repolish:off:commands -->

Each command has its own page with the full argument table (generated from the
command's parameter model), the pipeline it runs, and the special cases worth
knowing, such as running it in CI.
