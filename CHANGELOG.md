# Changelog

All notable changes to this project will be documented in this file.

This changelog is automatically generated using
[git-cliff](https://git-cliff.org/) from commit messages following
[Conventional Commits](https://www.conventionalcommits.org/).

View [unreleased changes][unreleased] since the last release.

## [0.6.0] <a name="0.6.0" href="#0.6.0">-</a> February 12, 2026

### 🚀 Features

- Implement multiregex preprocessor (#21) by
  [@jmlopez-rod](https://github.com/jmlopez-rod) in
  [#21](https://github.com/hotdog-werx/repolish/pull/21)
- Add providers orchestration and auto-directory resolution (#23) by
  [@jmlopez-rod](https://github.com/jmlopez-rod) in
  [#23](https://github.com/hotdog-werx/repolish/pull/23)
- Strip .jinja extension from template filenames (#24) by
  [@jmlopez-rod](https://github.com/jmlopez-rod) in
  [#24](https://github.com/hotdog-werx/repolish/pull/24)

### 🐛 Bug Fixes

- Fix broken symlink handling and improve test organization (#25) by
  [@jmlopez-rod](https://github.com/jmlopez-rod) in
  [#25](https://github.com/hotdog-werx/repolish/pull/25)

[0.6.0]: https://github.com/hotdog-werx/repolish/compare/0.5.0...0.6.0

## [0.5.0] <a name="0.5.0" href="#0.5.0">-</a> January 30, 2026

### 🚀 Features

- Add repolish-debugger CLI tool for preprocessor debugging (#19) by
  [@jmlopez-rod](https://github.com/jmlopez-rod) in
  [#19](https://github.com/hotdog-werx/repolish/pull/19)

[0.5.0]: https://github.com/hotdog-werx/repolish/compare/0.4.0...0.5.0

## [0.4.0] <a name="0.4.0" href="#0.4.0">-</a> January 29, 2026

### 🚀 Features

- Enhanced context system with passing and overrides (#16) by
  [@jmlopez-rod](https://github.com/jmlopez-rod) in
  [#16](https://github.com/hotdog-werx/repolish/pull/16)

### 🐛 Bug Fixes

- Handle binary files in templates without crashes (#17) by
  [@jmlopez-rod](https://github.com/jmlopez-rod) in
  [#17](https://github.com/hotdog-werx/repolish/pull/17)

[0.4.0]: https://github.com/hotdog-werx/repolish/compare/0.3.4...0.4.0

## [0.3.4] <a name="0.3.4" href="#0.3.4">-</a> January 28, 2026

### 🐛 Bug Fixes

- Ensure regex processors use mapped destination for `_repolish.*` templates
  (#13) by [@jmlopez-rod](https://github.com/jmlopez-rod) in
  [#13](https://github.com/hotdog-werx/repolish/pull/13)

[0.3.4]: https://github.com/hotdog-werx/repolish/compare/0.3.3...0.3.4

## [0.3.3] <a name="0.3.3" href="#0.3.3">-</a> January 25, 2026

### 🐛 Bug Fixes

- Support conditional files (_repolish.*) in nested subdirectories (#10) by
  [@jmlopez-rod](https://github.com/jmlopez-rod) in
  [#10](https://github.com/hotdog-werx/repolish/pull/10)
- Set colors in CI and do not crop content (#11) by
  [@jmlopez-rod](https://github.com/jmlopez-rod) in
  [#11](https://github.com/hotdog-werx/repolish/pull/11)

[0.3.3]: https://github.com/hotdog-werx/repolish/compare/0.3.2...0.3.3

## [0.3.2] <a name="0.3.2" href="#0.3.2">-</a> January 18, 2026

### ⚙️ Miscellaneous Tasks

- Use latest changes from codeguide (#8) by
  [@jmlopez-rod](https://github.com/jmlopez-rod) in
  [#8](https://github.com/hotdog-werx/repolish/pull/8)

[0.3.2]: https://github.com/hotdog-werx/repolish/compare/0.3.1...0.3.2

## [0.3.0] <a name="0.3.0" href="#0.3.0">-</a> November 11, 2025

### 🚀 Features

- Conditional files by [@jmlopez-rod](https://github.com/jmlopez-rod)
- Add create_only_files for initial scaffolding preservation by
  [@jmlopez-rod](https://github.com/jmlopez-rod)

### 🐛 Bug Fixes

- Allow file deletions by [@jmlopez-rod](https://github.com/jmlopez-rod)

[0.3.0]: https://github.com/hotdog-werx/repolish/compare/0.2.2...0.3.0

## [0.2.1] <a name="0.2.1" href="#0.2.1">-</a> October 28, 2025

### 🐛 Bug Fixes

- New template contents ignored/removed (#3) by
  [@jmlopez-rod](https://github.com/jmlopez-rod) in
  [#3](https://github.com/hotdog-werx/repolish/pull/3)

[0.2.1]: https://github.com/hotdog-werx/repolish/compare/0.2.0...0.2.1

## [0.1.1] <a name="0.1.1" href="#0.1.1">-</a> October 17, 2025

### 🐛 Bug Fixes

- Missing pydantic dependency by [@jmlopez-rod](https://github.com/jmlopez-rod)

[0.1.1]: https://github.com/hotdog-werx/repolish/compare/0.1.0...0.1.1

## [0.1.0] <a name="0.1.0" href="#0.1.0">-</a> October 17, 2025

### 🚀 Features

- Setup project and create configuration and loader by
  [@jmlopez-rod](https://github.com/jmlopez-rod)
- Add tag and regex text processors by
  [@jmlopez-rod](https://github.com/jmlopez-rod)
- Add anchor dictionary by [@jmlopez-rod](https://github.com/jmlopez-rod)
- Allow other optional prefixes by
  [@jmlopez-rod](https://github.com/jmlopez-rod)
- Create provider by [@jmlopez-rod](https://github.com/jmlopez-rod)
- Create final provider and include history on file deletion decisions by
  [@jmlopez-rod](https://github.com/jmlopez-rod)
- Add example and update README by
  [@jmlopez-rod](https://github.com/jmlopez-rod)
- Complete repolish by [@jmlopez-rod](https://github.com/jmlopez-rod)

### 💼 Other

- Fix rendering issues by [@jmlopez-rod](https://github.com/jmlopez-rod)

### 🚜 Refactor

- Consolidate cookiecutter staging and tighten tests/typing by
  [@jmlopez-rod](https://github.com/jmlopez-rod)

### ⚙️ Miscellaneous Tasks

- Rearrange example by [@jmlopez-rod](https://github.com/jmlopez-rod)

[0.1.0]: https://github.com/hotdog-werx/repolish/tree/0.1.0
[unreleased]: https://github.com/hotdog-werx/repolish/compare/0.5.0...HEAD
