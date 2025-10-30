# Changelog

## 2025-10-30 — Behavior change: ignore line-ending-only diffs by default

- By default `repolish --check` now ignores differences that are only line
  ending related (CRLF vs LF). This avoids spurious failures on Windows where
  files are checked out with CRLF but the canonical template uses LF. The
  comparison normalizes newlines to LF before comparing file contents so
  platform-specific line endings do not cause `--check` to fail.

- If you need to make line-ending differences visible (for example during a
  provider release where exact bytes matter), set the environment variable
  `REPOLISH_PRESERVE_LINE_ENDINGS=1` (or `true`) to opt into preserving original
  line endings when producing unified diffs.

This change makes `--check` more platform-agnostic while still offering an
opt-out when exact bytes must be enforced.
