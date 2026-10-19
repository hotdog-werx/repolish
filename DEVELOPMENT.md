# Development Modes: repolish + devkit

Repolish development is provider-independent by default: the test suite,
fixtures, and e2e harness in this repo are the gate, and no devkit checkout is
ever needed to work on repolish itself.

The devkit provider enters only for dogfooding: when a repolish feature changes
the provider-facing surface (a new API providers consume, like facets), it is
worth exercising it through a real consumer before release. The facets
test-drive earned its keep: it surfaced the link-message guessing, the
generated-header naming, and the link directory naming assumption, all fixed
before shipping. This guide defines the modes for that dogfooding and how to
switch between them.

The key rule in every mode:

- `repolish` is always the local editable checkout in this repo. The mode axis
  is only the `hotdogwerx-devkit-workspace` source.
- A dependency solve must see exactly one `repolish` source. Conflicts come from
  the provider side leaking its own repolish pin (see
  [Troubleshooting](#troubleshooting)), not from keeping `repolish` local here.

Both switches are commented toggle lines in the tracked files, so a mode change
is a comment move, never a rewrite:

- repolish repo: the `hotdogwerx-devkit-workspace` source in
  [uv-toolbox.yaml](uv-toolbox.yaml) (active git lines vs the commented
  `path`/`editable` lines below them).
- devkit repo: the `[tool.uv.sources]` override in `pyproject.toml` (two
  commented lines above `tool.releez`).

## Mode 1: Local Co-Development (both repos are changing)

Use this mode when editing repolish and devkit together.

repolish repo: in [uv-toolbox.yaml](uv-toolbox.yaml) comment out the git lines
of the `hotdogwerx-devkit-workspace` source and uncomment the `path`/`editable`
lines, then re-lock and reinstall:

```bash
uvtb lock
uvtb install
```

devkit repo: uncomment the two `[tool.uv.sources]` override lines, then
re-resolve:

```bash
uv lock --upgrade-package repolish
uv sync
```

The override wins over the dev group's branch pin (uv resolves `repolish` as a
local path), so the two toggle lines are the whole switch on the devkit side.
Both repos now see each other's working trees: change repolish and the providers
together, run both suites, and dogfood `repolish apply` against the current
state of both.

## Mode 2: PR Staging / GitHub Integration Test

Use this mode to test what the published branch experience looks like. This is
the mode [uv-toolbox.yaml](uv-toolbox.yaml) is committed in.

repolish repo: leave the git lines active (commented `path` lines stay
commented), then re-lock and reinstall as above. `repolish` stays your local
editable checkout; devkit-workspace comes from the branch, exactly what a
consumer resolving it from git gets.

devkit repo: leave the override commented. Its dev group carries the branch pin
(`repolish @ git+...@topic/facets-recreate`) as a direct URL, which is what
supplies unreleased repolish features to devkit's own venv in this mode.
Re-resolve as in Mode 1 when the branch moves.

A fresh clone gets this mode working through `mise run setup`, which installs
the envs, runs `repolish link`, and refreshes `ty.toml`'s site-packages path.

## Mode 3: After Publishing repolish

Use this mode once repolish is published with the needed features.

devkit repo: drop the dev group's branch pin back to the plain requirement
(`repolish`) or remove it, and delete the override toggle lines.

repolish repo: the `hotdogwerx-devkit-workspace` source entry disappears
entirely; the plain dependency resolves the published package from PyPI.

Then re-lock and sync both repos as above.

## Dogfooding in this repo

- `mise run workspace:repolish` applies repolish to this repo through the uvtb
  `repolish` env (the devkit-workspace gitignore facet and the local provider
  both run).
- `mise run workspace:repolish:check` is the drift gate; `mise run
  ci-checks`
  includes it.
- Any other command runs through the env, e.g.
  `uvtb exec --env repolish -- repolish link`.

## Quick Switch Checklist

1. Pick the mode first, then flip the toggles in both repos (they must agree:
   Mode 1 enables both local forms, Mode 2 leaves both git/branch forms).
2. Re-lock and reinstall here (`uvtb lock && uvtb install`), re-resolve in
   devkit (`uv lock --upgrade-package repolish && uv sync`).
3. Expect lock churn on every switch (`uv-toolbox.lock` here, `uv.lock` in
   devkit) and a new venv path in `ty.toml` when the env rebuilds;
   `mise run
   setup` (or its `local-cli venv` step) refreshes it.
4. Never push devkit with its override enabled: a workspace-root
   `[tool.uv.sources]` override leaks into every consumer resolving a member
   package from git and breaks their installs.

## Troubleshooting

`Requirements contain conflicting URLs for package repolish` means one solve saw
two repolish sources. Two shapes:

- Both URLs point at your machine: the toggles disagree. Return to checklist
  step 1.
- One URL is a git URL with a subdirectory escaping the checkout
  (`#subdirectory=../../../...`): the provider's workspace root declares a local
  path source for repolish, and uv rewrote it relative to its checkout. The fix
  is in the provider repo, not here: unreleased-feature pins belong in the dev
  group as direct URL requirements (they never leak into consumers), never in
  `[tool.uv.sources]` on the workspace root.
