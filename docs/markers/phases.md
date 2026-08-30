# Phases: pre-render and after-render

Directives run in two phases — `pre-render` (default, on staged templates
before Jinja) and `after-render` (opt-in via `|after-render` in the tag, on
rendered output) — which matters when directives live inside loop-generated or
conditional template content.

<!-- Align with: tests/directives/test_file_api.py, tests/integration/test_directives_after_render.py, tests/directives/test_keep_processors.py phase-suffix cases -->
