# Part 3 — The Sync Problem

The two providers work. You publish them to PyPI, link them to your five
projects, and life is good for a few weeks. Then you hit the wall.

## How it starts

A colleague asks for `check-basedpyright` in the Python provider. You add it,
bump the version, and push `devkit-python` to its repository. Then you tag a
release of `devkit-workspace` for a dependency order reason that only made sense
at 11 pm. Now to update any project you have to:

1. Pull `devkit-workspace`, build it, bump the version reference.
2. Pull `devkit-python`, update its `devkit-workspace` dependency, build it,
   bump the version reference.
3. In each consumer project: update both provider versions in `pyproject.toml`,
   run `uv sync`, run `repolish apply`, check the diff.

Five projects. Two providers. Every non-trivial change ripples through this
chain. The providers cannot be tested together before being published because
they live in separate repos and you cannot easily install one from the other's
work-in-progress branch.

## The concrete pain points

**Circular-feeling dependencies.** `devkit-python` imports `WorkspaceInputs`
from `devkit-workspace`. If the workspace provider's input schema changes, you
must update the Python provider immediately and release both together. With
separate repos, "releasing together" means careful branch coordination, version
bumps in two places, and a brief window where PyPI has a broken combination
published.

**Testing is integration testing across repos.** To verify that the python
provider's `provide_inputs` output actually reaches the workspace provider's
`finalize_context`, you need both installed. You could add the other package as
a dev dependency and install from git, but then you are managing two dev
dependency chains and CI becomes complicated.

**Consumer projects drift differently.** Each project pins its own provider
versions. After three months your five projects are running different versions
of the workspace provider with a mix of configs that were each correct at the
time they were applied but are now inconsistent with each other.

**The feedback loop is too long.** The cycle of "edit provider → build → publish
dev release → install in test project → apply → check diff" takes longer than
the edit itself. You start batching changes to amortise the overhead, which
means bigger, harder-to-review diffs and more opportunities for mistakes.

## The realisation

The pain is not fundamental to the approach — the providers themselves are a
good idea. The problem is that they are artificially separated. They were put in
different repos because that felt like the "one package per repo" right thing to
do, not because they need to be independent.

They are not independent. They share a message contract (`WorkspaceInputs`).
They are always deployed together. Their tests need to run together. Their
versions should be tied together.

What if they lived in the same repository?

The tags `devkit-workspace:v0.2.0` and `devkit-python:v0.1.0` represent the last
state of the two-repo setup. Part 4 starts fresh from those baselines and merges
them into a single `devkit` monorepo.

---

Next: [Part 4 — Going Monorepo](04-monorepo.md)
