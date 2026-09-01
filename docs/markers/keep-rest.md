# Keep the Rest

**Aliases:** `repolish:keep-the-rest`, `repolish:keep-footer`.

Everything from a marker line **to the end of the file** comes from your project
file; the provider manages the head. This is the [keep block](keep-block.md)
with its end implied — and the direct descendant of the tail-capture regex that
the multiregex workflow kept needing ("let me append my own tools after yours").
The marker line names the intention instead of hiding it in a pattern.

The classic case: `.gitignore`, where the provider ships canonical ignores and
the project's own entries accumulate at the bottom.

<!-- Align with: tests/directives/test_keep_processors.py; example validated with repolish preview -->

## Worked example

=== "Template"

    `repolish/.gitignore.jinja` — provider-managed head, developer-owned tail:

    ```gitignore
    .venv/
    __pycache__/
    ## repolish:keep-rest[tail] marker="## mine"
    ## mine
    # add your own below
    ```

=== "Your file"

    `.gitignore` — your entries are already there:

    ```gitignore
    .venv/
    ## mine
    .idea/
    scratch/
    ```

=== "Try it"

    Save this as `scratch.yaml`:

    ```yaml
    template: |
      .venv/
      __pycache__/
      ## repolish:keep-rest[tail] marker="## mine"
      ## mine
      # add your own below

    target: |
      .venv/
      ## mine
      .idea/
      scratch/
    ```

    and run:

    ```bash
    repolish preview scratch.yaml
    ```

=== "Result"

    The head is refreshed from the template; everything from `## mine` down is
    untouched:

    ```gitignore
    .venv/
    __pycache__/
    ## mine
    .idea/
    scratch/
    ```

## Behavior

- If your file has no marker line, the template default tail ships — so fresh
  projects still get a sensible file.
- The marker line itself is preserved in the output; only the directive line is
  stripped.
- Supports the [`|after-render` phase](phases.md).
- Compose it with [multiregex](multiregex.md#adding-your-own-own-the-tail) to
  get "provider owns the values, developers own the tail" in one file — the
  exact lineage that led to keep blocks in the first place.
