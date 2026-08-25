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

`repolish scaffold --local` generates this structure for you — a `repolish.py`
entry point with a ready `Provider` subclass and a sample template under
`repolish/`. By convention it goes to `internal/` (sibling to `src/`: code that
only maintains this repo, never shipped); the provider is aliased `local` and
named `LocalProvider`. No `--package` name is needed — local providers are not
packages — and no directory either, `internal/` is the default:

```bash
repolish scaffold --local
```

```
internal/
  templates/
    repolish.py                     ← LocalProvider entry point
    repolish/some-template.md.jinja ← sample template
```

The command prints the `providers:` snippet to paste into `repolish.yaml`:

```yaml
providers:
  local:
    provider_root: internal/templates
```

The flat layout above is self-contained (repolish loads `repolish.py` by file
path, so sibling imports are unavailable). Once you outgrow a single file,
`repolish scaffold --local --installable` switches to the installable tier:
`repolish.py` becomes a shim over an editable-installed `internal/` package. See
[repolish scaffold](../reference/scaffold.md#local-provider-layout) for details.
