# Repolish

> Repolish is a hybrid of templating and diff/patch systems, useful for
> maintaining repo consistency while allowing local customizations. It uses
> templates with placeholders that can be filled from a context, and regex
> patterns to preserve existing local content in files.

!!! warning "Cookiecutter deprecation & migration (planned for v1)"

    Cookiecutter-based final rendering will be removed in the v1 release. You
    can migrate now by enabling the opt‑in native Jinja renderer
    (`no_cookiecutter: true`) and validating your templates with
    `repolish preview`.

    Why migrate
    - Jinja avoids Cookiecutter CLI/option quirks (arrays treated as options),
      provides stricter validation (`StrictUndefined`) and clearer error
      messages, and enables new features such as `tuple`-valued
      `file_mappings` (per-file extra context).

    Quick migration steps
    1. Enable `no_cookiecutter` and run `repolish apply`.
    2. Update templates to prefer top-level context access
       (`{{ my_provider.* }}`) — the `cookiecutter` namespace remains available
       during migration.
    3. Follow the examples in the Templates guide (`guides/templates.md`).

    See also: [Loader context](configuration/context.md) for `file_mappings`
    examples.

## Documentation

- [Getting Started](getting-started/)
- [CLI Commands](cli.md)
- [Preprocessors](guides/preprocessors.md)
- [Provider Patterns](guides/patterns.md)
- [Debugging Preprocessors](guides/debugger.md)
