# Insertions

Insertions grew out of validators. Validators came first: in some cases
developers weren't ready to let repolish _touch_ a file, but they still wanted
its value — so they handed over a function that **inspects** the file instead
("make sure I did this"). Once that existed, the follow-up was obvious: the same
kind of function can _write_ instead of check. "I like my file, I'll maintain it
— but here is a space you can fill."

That is the insertion block: a marked region in **your** file whose body a
provider function regenerates on every apply. It's where docs-in-sync-with-code
came from — instead of manually copying a class's fields or a CLI's options into
a README, a function reads the code directly and writes the section. Add a
field, run repolish, the docs follow.

<!-- Align with: tests/integration/test_insertions.py, tests/insertions/; worked example validated end-to-end with a scratch project (preview does not simulate insertions) -->

## The block

```html
<!-- repolish:on:config config-options -->
<!-- repolish:off:config -->
```

An `on`/`off` pair reserves the region between them:

- `config` — the tag (optional visual aid for matching pairs).
- `config-options` — the function the provider registered for this file.
- Anything after the function name is passed to it as arguments.

The body between the markers is **always regenerated** by the function on each
apply — put nothing there yourself. Use whatever comment syntax the file type
supports (`#`, `//`, `<!-- -->`, …); the tag and colon are optional. Full syntax
variations in the
[provider insertions guide](../provider-development/insertions.md#marker-format).

## Worked example

Keeping a README's configuration section in sync with the options model — you
own the README, the provider fills one block. Note this example uses the **your
file** flow; a template can ship the same markers too (see
[Template-shipped blocks](#template-shipped-blocks)).

=== "Provider code"

    `demo_provider/repolish.py` — registers the function for `README.md`:

    ```python
    from pydantic import BaseModel, Field

    from repolish import BaseContext, BaseInputs, Provider


    class Options(BaseModel):
        """CLI options for the demo tool."""

        line_length: int = Field(88, description='Max line length for formatters')
        target_python: str = Field('3.12', description='Python target version')
        strict: bool = Field(True, description='Fail on warnings')


    class Ctx(BaseContext):
        pass


    class Demo(Provider[Ctx, BaseInputs]):
        def create_context(self):
            return Ctx()

        def create_file_insertions(self, context):
            def config_options(brief: str = '') -> str:
                if brief == 'yes':
                    return '\n'.join(f'- `{name}`' for name in Options.model_fields)
                return '\n'.join(
                    f'- `{name}` — {f.description} (default: `{f.default}`)'
                    for name, f in Options.model_fields.items()
                )

            return {'README.md': {'config-options': config_options}}
    ```

=== "Your file"

    `README.md` — you write the block once:

    ```markdown
    # Demo project

    ## Configuration

    <!-- repolish:on:config config-options -->
    <!-- repolish:off:config -->
    ```

=== "Try it"

    [`repolish preview`](../reference/preview.md) does not simulate insertions
    (it runs the pre-render phase only), so this sandbox is a scratch project:

    ```bash
    mkdir insertion-demo && cd insertion-demo
    git init
    ```

    `repolish.yaml`:

    ```yaml
    providers:
      demo:
        provider_root: ./demo_provider
    ```

    Create `demo_provider/repolish.py` and `README.md` from the other tabs,
    then:

    ```bash
    repolish apply
    ```

=== "Result"

    The block is filled from the model — and stays in sync as fields are added:

    ```markdown
    # Demo project

    ## Configuration

    <!-- repolish:on:config config-options -->
    - `line_length` — Max line length for formatters (default: `88`)
    - `target_python` — Python target version (default: `3.12`)
    - `strict` — Fail on warnings (default: `True`)
    <!-- repolish:off:config -->
    ```

## Template-shipped blocks

The same block works inside a **provider-rendered file**: the template emits the
`on`/`off` markers and registers the function for that same path. The markers
are not directive syntax, so they pass through both directive
[phases](phases.md) and Jinja rendering untouched, and the insertion phase fills
the body after the file lands on disk.

```html title="repolish/README.md.jinja"
## Status

<!-- repolish:on:status render-status ready -->
<!-- repolish:off:status -->
```

One mechanism, two flows: you ship the block in a file you own, or the template
ships it in a file the provider renders.

## Editing the block

The marker line is yours to edit, even in a template-shipped block — change the
function or its arguments, and the next apply **adopts** your marker (matched by
tag and occurrence order) while still regenerating the body.

In the worked example, change the marker to `config-options yes` and re-apply:

```markdown
<!-- repolish:on:config config-options yes -->

- `line_length`
- `target_python`
- `strict`

<!-- repolish:off:config -->
```

Adopted markers make the output stable: `repolish apply --check` reports no
drift afterward.

!!! note "What adoption doesn't do" Only the **marker line** is adopted. The
body is always the function's output — hand-edits inside the block are replaced
on the next apply. If you want a region the provider must not touch at all,
that's a [keep block](keep-block.md) — which needs a template, since only
templates reconcile regions.

## Timing

Insertions run after files are written to disk and before post-processing
(formatters see the final content) — see the
[full pipeline](phases.md#the-full-pipeline). Insertion content is covered by
check mode: stale blocks fail `repolish apply --check` like template drift.

For the provider side — function signatures, keyword-only context injection,
disabling or extending insertions via `overrides` — see the
[provider insertions guide](../provider-development/insertions.md).
