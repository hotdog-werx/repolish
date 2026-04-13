# Installation

## Recommended: mise + uvx

If you are starting fresh - whether you are creating a new project or writing a
new provider - the easiest path is [`mise`](https://mise.jdx.dev). `mise` is a
polyglot tool manager that handles Python, Node, Go, and more from a single
config file. You drop a `mise.toml` in your repo and everyone on the team gets
the exact same toolchain without touching their system Python.

Install `mise` once:

```bash
curl https://mise.run | sh
```

Then add a minimal `mise.toml` to your repo:

```toml
[settings]
experimental = true
python.uv_venv_auto = true

[tools]
uv = "latest"
```

`experimental = true` unlocks the `python.uv_venv_auto` setting, which tells
mise to auto-activate the `uv`-managed virtualenv whenever you enter the
directory. Without it, `repolish` and other project tools won't be found on your
PATH after `uv sync`.

Run `mise trust && mise install` and `uv` is available. From there you can use
`uvx` to run repolish without adding it to any virtual environment:

```bash
mise trust && mise install
uvx repolish --help
```

`uvx` fetches and caches the latest published repolish release and runs it in an
isolated environment. This is how the [tutorial](../tutorial/index.md) works -
you never have to configure a virtualenv just to get started.

## Traditional install

If you already have Python 3.11+ and prefer a direct install:

=== "pip"

    ```bash
    pip install repolish
    repolish --help
    ```

=== "uv"

    ```bash
    uv add repolish
    repolish --help
    ```

`repolish` includes the full CLI - `repolish apply`, `repolish check`,
`repolish link`, `repolish scaffold`, and `repolish preview` - no additional
install steps are needed.

## Next steps

- [Quick Start](quick-start.md) - set up your first `repolish.yaml` and run a
  check
- [Tutorial](../tutorial/index.md) - a step-by-step walkthrough that uses the
  mise + uvx path throughout
- [Configuration](../configuration/overview.md) - full `repolish.yaml` reference
