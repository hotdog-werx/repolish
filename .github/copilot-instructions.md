# Quick guidelines for AI agents and contributors

- Use `@dataclass` for grouped parameters (`RenderContext` is an example).
- Break logic into small, focused helpers (`_choose_ctx_for_file`, etc.).
- Keep helpers private (underscore prefix) unless they are intended for reuse
  across modules.
- Do not test helpers directly; test the public functions that use them.
- Markdown must be plain MkDocs‑compatible; single backticks only, no Sphinx
  double-backticks or directives.
- Python style:
  - imports at top
  - `poe format` before running tests or other checks
  - `poe ci-checks` for lint/typing/complexity/coverage
- Comments/docstrings explain what/how, not historical rationale.
- Parameterized tests: wrap each case in a `TCase` dataclass, use
  `ids=lambda c: c.name`; function names in snake_case.
- Logging: structured events with sufficient context (paths/providers); when
  re-raising, annotate with file/path info.
