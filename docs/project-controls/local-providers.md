# Local Providers

A local provider lets you replace an upstream provider's templates and context
logic with your own, entirely within your project. This is the highest level of
control: you are not patching a value or pausing a file, you are supplying a
completely different implementation.

## When to use this

- A provider ships a template that fundamentally does not fit your project and
  no amount of context patching will fix it.
- You need to prototype a provider before publishing it as a package.
- You want to fork a provider and iterate locally before upstreaming the
  changes.
- You want a "vendor copy" of a provider that you own independently of the
  upstream release cadence.

## How it works

Set `provider_root` on a provider entry to point at a local directory that
contains the same structure as any other provider — a `repolish/` template tree
and, optionally, a `repolish.py` module. The blessed location is `internal/` at
the repo root (sibling to `src/`): a home for code that only maintains this repo
and never ships — not under `src/` (that would tie it to the project's install
boundary) and not under `.repolish/` (ephemeral, gitignored):

```
myproject/
  internal/                ← blessed home for repo-maintenance code
    mycorp/                ← this is your provider_root
      repolish.py          ← optional: create_context, create_anchors, etc.
      repolish/
        pyproject.toml     ← your templates
        .github/
          workflows/
            ci.yml
  repolish.yaml
```

```yaml
# repolish.yaml
providers:
  codeguide:
    provider_root: internal/mycorp
```

Repolish resolves `provider_root` relative to `repolish.yaml`. If no
`provider-info.json` file is found in the standard location, repolish falls back
to this directory for both templates and context.

## Full replacement vs fallback

There are two patterns depending on whether you also set `cli`:

### Full local replacement (no `cli`)

```yaml
providers:
  codeguide:
    provider_root: internal/mycorp
```

No CLI command is run. Repolish uses the local directory as the sole source of
templates and context. The upstream package is not involved at all.

### Fallback (with `cli`)

```yaml
providers:
  codeguide:
    cli: codeguide-link
    provider_root: internal/mycorp
```

Repolish runs the CLI first. If a `provider-info.json` is found (meaning the CLI
installed the provider normally), the local `provider_root` is ignored and a
warning is logged. If the CLI is not installed or produces no info file, the
local directory is used as a fallback.

!!! note

    When both `cli` and `provider_root` are set and a provider-info file
    _is_ found, repolish logs a `provider_root_ignored` warning to tell you the
    local directory is not being used.

## The `resources_dir` separation

By default `resources_dir` equals `provider_root`. If your local provider
separates its template tree from its linked resources (for symlinks, config
files, etc.) you can set them independently:

```yaml
providers:
  codeguide:
    provider_root: internal/mycorp/templates # repolish.py lives here
    resources_dir: internal/mycorp # root for symlinked resources
```

## Minimum required structure

A valid local provider needs at least a template directory:

```
provider_root/
  repolish/            ← templates go here (required)
    some_file.txt
  repolish.py          ← optional; omit if no context/anchors needed
```

Without `repolish.py` the provider supplies templates only — context will be
empty and no anchors will be defined. That is enough to override specific files.

## Scaffolding a local provider

`repolish scaffold --local` generates this structure for you: a `repolish.py`
entry point re-exporting a ready `Provider` subclass, a sample template under
`repolish/`, and an editable-installed `local_provider/` package holding the
real code. By convention it goes to `internal/` (sibling to `src/`: code that
only maintains this repo, never shipped); the provider is aliased `local` and
named `LocalProvider`. No `--package` name is needed and no directory either,
`internal/` is the default:

```bash
repolish scaffold --local
```

```
internal/
  pyproject.toml                    ← editable-install this (declares local-cli)
  local_provider/
    provider.py                      ← LocalProvider / LocalProviderContext
    cli.py                           ← fast-lane CLI wiring
  templates/
    repolish.py                      ← shim re-exporting from local_provider
    repolish/some-template.md.jinja  ← sample template
```

The command prints the `providers:` snippet to paste into `repolish.yaml`:

```yaml
providers:
  local:
    provider_root: internal/templates
```

Add `--flat` for the zero-install variant: a single self-contained
`templates/repolish.py` with the CLI beside the root and no `pyproject.toml`
(repolish loads `repolish.py` by file path, so sibling imports are unavailable).
The `repolish.yaml` wiring is identical for both tiers. See
[repolish scaffold](../reference/scaffold.md#local-provider-layout) for details.

## Fast lanes

A local provider gets the same generated fast-lane CLI a package ships: the
scaffold wires `provider_cli` to the stated `provider_root` that discovery
cannot find, and lanes declared on the provider class become subcommands. The
CLI lives inside the provider package (`internal/local_provider/cli.py`), and
its pyproject declares it as the `local-cli` console script, so after the
editable install lanes run from anywhere:

```bash
local-cli <lane>
```

The flat tier writes `internal/cli.py` instead; run it from the project root:

```bash
python internal/cli.py <lane>
```

That file sits beside the provider root, not inside it: running a file as a
script puts its directory first on `sys.path`, where the provider's
`repolish.py` would shadow the `repolish` package itself. A stated root carries
the same semantics the config gives it: `resources_dir` defaults to the root
itself and a config entry whose `provider_root` points at the same directory
still names the run. See
[the CLI docs](../provider-development/fast-lanes/cli.md#local-providers) for
the full behavior.
