# CLI

`provider_cli` builds a cyclopts app with one subcommand per lane plus an `all`
subcommand that runs the provider's full pass (still fast: single provider load,
no dry pass). New lanes need no `pyproject.toml` edits because the subcommands
are generated from the hook.

That generated CLI is the feature worth noticing. A provider author does not
need a second package, separate parser setup, or hand-maintained subcommand
table just to expose useful project commands. The provider already owns the
templates, knows the standards, and has a place to declare lane-specific
context. `provider_cli` turns that into a real project tool with almost no extra
surface area.

Each subcommand takes the apply flags: `--config`, `--check`,
`--skip-post-process`, `--fail-on-warnings`, and `-v`. The flag set lives in the
parameter model the `repolish apply` command itself uses, so a flag added there
shows up on lane subcommands too; the two CLIs cannot drift apart.

The CLI runs in any project, registered or not. When a `repolish.yaml` exists
the lane run reads it, but only for the keys a lane run needs (the table below);
provider loading, registration, and link commands never run, so no
`repolish link` is ever required. Without a config file, or when the config does
not list the provider, the run is built in memory around the package the CLI is
running from.

The provider's identity in `repolish.provider.alias` is provider-owned: pass
`alias=` to `provider_cli` and that name is used everywhere, in rendered headers
and logged events alike, whether or not the config lists it. Without an explicit
alias, a config entry whose `provider_root` points at the package's
`resources/templates` directory names the run. A run with no match falls back to
the package name (the directory holding `resources/`): fine for bookkeeping, but
it changes if the package is renamed, so `alias=` is the stable choice for
headers. An alias like `kitkat-databricks-cli` is entirely up to the provider
developer; repolish never invents one.

## What a lane run reads from the config

| key                                      | honored    | notes                                                         |
| ---------------------------------------- | ---------- | ------------------------------------------------------------- |
| `paused_files`                           | yes        | applies to lane dests and copies                              |
| `fast_lanes.resolutions`                 | yes        | coupled and decoupled lanes alike                             |
| `fast_lanes.config[<lane>].post_process` | yes        | replaces project post_process in named lane runs              |
| own entry fields                         | yes        | symlinks, `overrides`, `resources_dir`; the located root wins |
| `template_overrides`                     | yes        | keeps render parity                                           |
| project `post_process`                   | `all` only | named lanes run their own commands, or none                   |
| other providers                          | no         | never loaded, imported, or registered                         |
| `delete_files`                           | no         | lanes never delete                                            |

## Wiring the CLI into a provider

`repolish scaffold` generates this wiring for new providers. An established
provider adds it by hand once: one small module, one script entry, one
reinstall.

1. Create `mylib/repolish/cli.py` next to `linker.py`, exporting `main`:

```python
from repolish.fastlane import provider_cli

from mylib.repolish import MyProvider

main = provider_cli(MyProvider)
```

2. Register it as a console script in `pyproject.toml`, next to the linker
   entry:

```toml
[project.scripts]
mylib-link = 'mylib.repolish.linker:main'
mylib-cli = 'mylib.repolish.cli:main'
```

3. Reinstall the package the way the environment normally gets its console
   scripts (`uv pip install -e .`, `uv sync`, or the equivalent) so `mylib-cli`
   lands on `PATH`.

After that the CLI never needs touching again: subcommands come from
`create_fast_lanes`, so adding a lane later is a provider-code change only.

This is what makes lanes attractive even when the lane is not about "apply but
faster". A team can expose component generators, documentation updaters,
workflow bootstrappers, or one-off maintenance commands through the same
provider package they already ship for repolish.

## Trying a lane out

The smallest possible lane needs one template, one spec entry, and nothing else.
Add a template that lives entirely off `extra_context`, so it satisfies the
self-containment rule by construction:

```text
{{ message }}
```

The template lives at `mylib/resources/templates/repolish/hello.txt.jinja`,
alongside the provider's other templates. Declare the lane on the provider:

```python
def create_fast_lanes(self, repolish):
    return {
        'hello': FastLaneSpec(
            file_mappings={
                'hello.txt': TemplateMapping(
                    'hello.txt.jinja',
                    extra_context={'message': 'hi from the lane'},
                ),
            },
        ),
    }
```

From any project directory with the provider installed (no registration, link,
or config change needed; the new template is picked up from disk):

```
$ mylib-cli hello # writes hello.txt into the project
$ mylib-cli hello --check # exit 0: the lane output is stable
$ repolish apply --check # no drift on hello.txt: the full run agrees
```

If more than one config entry points at the same `resources/templates`
directory, the CLI resolves the first match; pass `alias=` in `cli.py` to pin
the provider's identity.
