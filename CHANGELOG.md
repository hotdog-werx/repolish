# Changelog

All notable changes to this project will be documented in this file.

This changelog is automatically generated using
[git-cliff](https://git-cliff.org/) from commit messages following
[Conventional Commits](https://www.conventionalcommits.org/).

View [unreleased changes][unreleased] since the last release.

## [0.3.2] <a name="0.3.2" href="#0.3.2">-</a> January 18, 2026

### ⚙️ Miscellaneous Tasks

- Use latest changes from codeguide (#8) by
  [@jmlopez-rod](https://github.com/jmlopez-rod) in
  [#8](https://github.com/hotdog-werx/repolish/pull/8)

[0.3.2]: https://github.com/hotdog-werx/repolish/compare/0.3.1...0.3.2

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
