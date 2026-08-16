# Provider anatomy

This is the page to start with when you are building or extending a provider. It
walks through the same shape repolish uses internally: configure the provider,
resolve it, build context, stage templates, render output, validate the final
files, and handle monorepo-specific behavior.

If you want the conceptual background before diving in, start with
[How It Works](../concepts/overview.md).

## The provider lifecycle

Every provider passes through the same rough pipeline:

1. [Provider Setup](config-file.md) — define the provider in `repolish.yaml`
2. [Provider Resolution](providers.md) — resolve `cli`, `provider_root`, and
   `resources_dir`
3. [Context & Inputs](context.md) — build typed context and share data between
   providers
4. [Templates](templates.md) — stage and render the canonical files
5. [Validators](validators.md) — enforce correctness after rendering
6. [Monorepo](monorepo.md) — handle root/member behavior and session wiring
7. [Testing Providers](testing.md) — verify provider behavior in isolation

## Common tasks

### I need to describe the provider in config

See [Provider Setup](config-file.md) and [Provider Resolution](providers.md).

### I need to author a Python provider

Start with [Context & Inputs](context.md), then continue to
[Templates](templates.md), [Preprocessors](preprocessors.md), and
[Validators](validators.md).

### I need to make the provider work in a monorepo

Read [Monorepo](monorepo.md) and [Mode Handlers](mode-handler.md).

### I need to validate the final rendered output

Use [Validators](validators.md). This is the place for post-render checks like
schema enforcement, file headers, and warnings vs hard failures.

### I need to test the provider without the full CLI pipeline

See [Testing Providers](testing.md).

## Start here

If you only read three pages, make them these:

1. [Provider Setup](config-file.md) — how the provider is declared and resolved
2. [Context & Inputs](context.md) — how a provider builds and shares state
3. [Templates](templates.md) — how provider content is staged and rendered

Then branch out to [Validators](validators.md) and [Monorepo](monorepo.md) once
those core concepts are clear.

## Related concept pages

- [How It Works](../concepts/overview.md)
- [Providers](../concepts/providers.md)
- [Templates](../concepts/templates.md)
- [Context](../concepts/context.md)
- [Preprocessors](../concepts/preprocessors.md)
- [Monorepo](../concepts/monorepo.md)
