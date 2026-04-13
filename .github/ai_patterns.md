# AI Agent Notes and Patterns

This short document is intended as a reference for AI models (including future
agents) working on this repository. It records recurring coding patterns, design
choices, and small reminders that help keep the codebase consistent and
maintainable.

## Dataclasses for grouped arguments

When a function or helper requires several related parameters, prefer wrapping
them in a `dataclass` rather than passing a long argument list or a plain
`dict`:

- Attributes are accessed via dot notation, giving better auto‑completion and
  avoiding key-name typos.
- The type checker can inspect the fields and warn about missing or incompatible
  values.
- Documentation is embedded in the class/field docstrings instead of spread
  across callers.

Example: the `RenderContext` dataclass holds rendering paths, the merged
context, providers, configuration, and a few flags. It replaces a handful of
ad‑hoc dictionaries used earlier and makes helper signatures much simpler.

## Prefer clear helpers over magic

Encapsulate logic in small, focused functions (e.g. `_choose_ctx_for_file`,
`_jinja_render`) rather than stuffing everything into one giant routine. This
makes tests easier to write and failures easier to diagnose.

## Markdown conventions

This project uses MkDocs, not Sphinx, so documentation should stick to plain
Markdown. Use single backticks for inline code literals and avoid reStructured
Text/Sphinx syntax like double backticks or directives. Keep formatting simple
and readable.

## Keep comments about usage, not history

Documentation strings and comments should explain _what_ a class or function
does and _how_ to use it. Historical rationale or background belongs in
changelogs or design notes, not in the primary docstring. That keeps the main
API documentation clean and stable.

## Parametrized tests with dataclasses

When writing PyTest parameterized tests, prefer wrapping each case in a
`@dataclass` (commonly named `TCase` when no other data classes appear in the
file) and supply a callable `ids` to convert objects into readable test IDs.
This keeps complex setups tidy and ensures each invocation has a descriptive
name without duplicating setup code.

Example pattern used in tests/loader/test_provider_inputs_flow.py:

```python
@dataclass
class TCase:
    name: str
    order: tuple[str, ...]
    expected: str

@pytest.mark.parametrize(
    "case",
    [
        TCase("A last -> B wins", ("provider_b",...), "provider_b"),
        TCase("A first -> default", ("provider_a",...), "provider_a"),
    ],
    ids=lambda c: c.name
)
def test_something(tmp_path: Path, case: TCase):
    ...
```

This is a recurring pattern in the repository, so future agents and
contributions should follow it. Test function names accompanying this pattern
should be simple and written in snake_case for readability.

## Logging and error handling

Use structured logs with descriptive event names and include enough context so
that users can trace back to the source of an error. When wrapping exceptions,
add file/path information before re-raising.

---

This file is a living guide; as we refactor and add features, feel free to
append other patterns or tips that future agents should know.
