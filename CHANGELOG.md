# Changelog

All notable changes to Sigil are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-05-28

First alpha release.

### Added

- Verb-first CLI (`sigil ask`, `sigil command`, `sigil run`, `sigil act`,
  `sigil events`, `sigil session`, `sigil install`, `sigil doctor`) with
  optional punctuation glyphs.
- Glyph routes: `,` (read-only answer), `,,` / `,,,` (one agent step), and `+`
  (explicit command execution with capture).
- zsh and Bash bindings installed via `sigil install`, with `--no-glyphs` for a
  punctuation-free setup.
- Event-sourced state under `~/.sigil/` with trust records (route, mode, risk
  labels, input lineage) inspectable through `sigil events` and
  `sigil events lineage`.
- `sigil doctor` environment checks for the `pi`, `glow`, and `sigil`
  executables, model endpoint reachability, model configuration, state
  writability, and shell binding installation.

[Unreleased]: https://github.com/rlouf/sigil/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/rlouf/sigil/releases/tag/v0.1.0
