# repolish

A hybrid templating and diff/patch system for maintaining repository consistency
while preserving local customizations.

Repolish applies provider-supplied templates to a project while using anchor
markers and regex patterns to preserve the parts that should remain local. It is
designed for teams that need to keep many repositories in sync without
overwriting developer customizations.

## Documentation

Full documentation is available at
[hotdog-werx.github.io/repolish](https://hotdog-werx.github.io/repolish).

- [Getting Started](https://hotdog-werx.github.io/repolish/getting-started/installation/) — install and run your first check
- [Configuration](https://hotdog-werx.github.io/repolish/configuration/overview/) — `repolish.yaml` reference
- [Preprocessors](https://hotdog-werx.github.io/repolish/guides/preprocessors/) — anchors, regex, and multiregex directives
- [Templates](https://hotdog-werx.github.io/repolish/guides/templates/) — file mappings and create-only files
- [Guides](https://hotdog-werx.github.io/repolish/guides/patterns/) — provider patterns and best practices
