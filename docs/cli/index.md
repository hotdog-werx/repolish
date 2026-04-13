# CLI Reference

repolish is invoked as a single top-level command with subcommands for each
operation. The global `-v` flag is available to all subcommands.

```
repolish [OPTIONS] COMMAND [ARGS]...
```

## Global options

| Flag | Description |
| --- | --- |
| `-v` | Increase verbosity. Pass once for structured log output, twice (`-vv`) for detailed debug messages. |
| `--version` | Print the installed version and exit. |
| `--help` | Show help and exit. |

## Commands

| Command | Description |
| --- | --- |
| [`apply`](apply.md) | Apply templates to the project. |
| [`link`](link.md) | Link provider resources into the project. |
| [`lint`](lint.md) | Lint a provider's templates against its context model. |
| [`preview`](preview.md) | Preview preprocessor output for a single template (debugger). |
| [`scaffold`](scaffold.md) | Scaffold a new provider package. |
