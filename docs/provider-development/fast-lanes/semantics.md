# Runtime Semantics

## Run semantics

What a lane run does:

- only the lane's `file_mappings`, `file_insertions`, and `file_validators` run;
  regular-hook content does not run in a lane
- the `repolish` namespace is injected exactly as in a full run, both into the
  hook and into rendered templates, so `{{ repolish.repo.owner }}` and
  `{{ repolish.provider.alias }}` render the same values either way
- copies and symlinks still materialize (they are context-free declarations and
  cheap to honor)
- lanes never delete: provider deletes and the config's `delete_files` key are
  skipped in lane runs

What a full `repolish apply` does with lanes: every coupled lane's contributions
are merged into the session bundle, so lane files render, insert, and validate
in the full run too. The same declarations run either way, which is why lane
output cannot drift from a full apply for lane files. Provider-owned one-off
flows are covered under [Commands](commands.md).

## Lazy lane factories

A provider with many lanes may want lane code loaded only when the lane actually
runs. `create_fast_lanes` may return zero-argument factories instead of specs:

```python
def create_fast_lanes(self, repolish):
    return {
        'actions': FastLaneSpec(...),  # eager is still fine
        'report': lambda: _build_report_spec(),  # imports deferred
    }
```

Factories are evaluated only where needed. Never at CLI construction: the
console script lists subcommands from lane names alone, so startup imports
nothing the provider did not already import. In a named lane run only the
selected lane's factory is evaluated. In a merged run (`repolish apply` or
`all`) every coupled factory is evaluated, because the full run needs each
lane's dests for collision detection.

## Per-lane post_process

A named lane inherits the project's top-level `post_process`: a lane's output
should land formatted the way the next full apply would format it, or that apply
churnes the file (and check mode flags it). A lane that needs different commands
declares its own list under `fast_lanes.config`, replacing the project's for
that lane — and an explicit empty list opts the lane out entirely, for when a
lane genuinely has no business running the project's formatters. `all` (and a
full `repolish apply`) always runs the project's commands.

```yaml
fast_lanes:
  config:
    actions:
      post_process:
        - ruff format {render_dir}
    python-only:
      post_process: [] # opt out of the project's formatters
```

Scoped entries (the `command`/`files` mapping form in the top-level
`post_process`) usually make per-lane config unnecessary: a lane's render tree
holds only the lane's files, so the runner keeps the formatters whose scope
matched and skips the rest. A lane generating only `.py` files runs the
project's Python formatter and skips dprint, no lane entry needed; the
`post_process: []` opt-out stays for lanes that have no business running any
formatter at all.

The commands run against the lane's render tree, in apply and `--check` mode
alike, so check still compares post-processed output.

## Collisions and resolutions

Duplicate dests are load-time errors, never silent overrides:

- The same dest in two coupled lane specs is a static authoring mistake: a
  merged run (`repolish apply` or `all`) raises naming both lanes, and there is
  no config escape hatch for it. Named lane runs do not pre-check it; only one
  lane runs, and checking would mean evaluating every factory. The full run
  catches the mistake.
- The same dest in a regular hook and a lane spec raises in whichever run mode
  hits it, naming the dest and both declaration sites. Regular mappings can be
  conditional on context, so a collision may surface only in some project
  states, through no authoring mistake the provider can fix. The project owner
  resolves it in `repolish.yaml`:

```yaml
fast_lanes:
  resolutions:
    'action1/action.yaml': fast_lane # the lane's version wins, everywhere
    'other/generated.txt': regular # the regular hook's version wins
```

`fast_lane` means the lane's contribution wins in full runs and lane runs alike;
`regular` means the regular contribution wins and lane runs skip the dest.
Whichever side wins does so consistently, so the parity guarantee holds either
way. The values are validated when the config is read, so a typo fails at
configuration loading, not mid-run.

The resolution is the project owner's choice because they own their files.
Repolish is meant to help, not to add friction: if a conditional mapping in an
upstream provider starts colliding with a lane, the project can decide locally
which version it wants without waiting on a provider release.
