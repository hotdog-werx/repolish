# Workflows

## Provider-owned scaffold commands

Imagine a provider that carries the team's React conventions. The team may not
want repolish to own every component file after creation, but they still want a
standard way to create new component modules. A provider command is a good fit:

- the provider already has the canonical templates,
- the generated CLI already exists,
- and the command can stay narrow to the developer workflow.

That looks like `react-provider-cli component`, not a separate bespoke tool. The
provider can render `Component.tsx`, `Component.test.tsx`, `Component.css`, or
any supporting files from the same template set the team already trusts. If the
provider also defines full-run templates for repo maintenance, both use cases
stay in one package rather than diverging across two systems.

## Bootstrap with a command, maintain with a lane

Provider commands and coupled fast lanes work well together when they share the
same template set.

- Use a provider command to create one new file or module immediately.
- Use a fast lane to discover those files later and keep them updated.
- Reuse the same templates in both paths so scaffolding and maintenance stay in
  sync.

This is useful when provider authors want a fast developer workflow for
bootstrapping new files without waiting for a full repo-wide apply. A command
can create the first version of a file directly, and a lane can later revisit
that file class and keep it aligned with the provider's current conventions.

React components are a good example. A `component` command can scaffold
`Component.tsx`, its test, and its stylesheet from the provider's templates.
Later, a lane can search for those component files and re-apply the same
template logic where appropriate, so the scaffold path and the maintenance path
reinforce each other instead of drifting apart.

This also avoids the older workflow where users had to create an empty file, run
repolish to populate it, and then run repolish again to converge on the final
state. Provider commands make that bootstrap step immediate, and fast lanes keep
the ongoing maintenance pass cheap.
