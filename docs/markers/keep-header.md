# Keep the Header

**Alias:** `repolish-keep-the-header`.

The mirror of [keep-rest](keep-rest.md): the developer owns the **top** of the
file, up to a marker line; the provider owns everything below it. Use it when a
file needs a project-written preamble — an introduction, a license note,
branding — but the machinery beneath should stay provider-managed.

<!-- Align with: tests/directives/test_keep_processors.py; example validated with repolish preview -->

!!! warning "Placement" The directive must be the **first line of the
template**. Placed later, it is ignored — by then content has already been
emitted, and honoring it would duplicate that content.

## Worked example

=== "Template"

    `repolish/PROJECT.md.jinja`:

    ```markdown
    ## repolish-keep-header[intro]: marker="## managed"
    # This project

    Intro the developer can edit.

    ## managed

    Provider-managed content below.
    ```

=== "Your file"

    `PROJECT.md` — your intro is already written:

    ```markdown
    # Acme Widgets

    Internal tooling for the widget pipeline.
    Ask #widgets on Slack before changing this file.

    ## managed

    stale provider content
    ```

=== "Try it"

    Save this as `scratch.yaml`:

    ```yaml
    template: |
      ## repolish-keep-header[intro]: marker="## managed"
      # This project

      Intro the developer can edit.

      ## managed

      Provider-managed content below.

    target: |
      # Acme Widgets

      Internal tooling for the widget pipeline.
      Ask #widgets on Slack before changing this file.

      ## managed

      stale provider content
    ```

    and run:

    ```bash
    repolish preview scratch.yaml
    ```

=== "Result"

    Your intro survives; everything from `## managed` down is refreshed from
    the template:

    ```markdown
    # Acme Widgets

    Internal tooling for the widget pipeline.
    Ask #widgets on Slack before changing this file.

    ## managed

    Provider-managed content below.
    ```

## Behavior

- If your file has no marker line, the template default header ships.
- Everything at or below the marker is provider-owned — edits there won't stick.
- Supports the [`|after-render` phase](phases.md).
