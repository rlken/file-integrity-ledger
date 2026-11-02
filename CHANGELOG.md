# Changelog

## 0.2.0 — 2026-11-02

- Windows support with PowerShell setup instructions that do not require activation.
- Binary file-descriptor reads preserve CRLF and control-Z bytes on Windows.
- Junctions and other reparse points produce explicit scan errors.
- Windows baseline creation preserves overwrite protection without requiring hard links.
- Windows/POSIX/UNC baseline roots can be inspected across platforms and checked with `--root`.
- Windows CI on Python 3.9 and 3.14, plus an isolated Windows wheel-install test.

## 0.1.0 — 2026-11-02

First public version.

- Recursive SHA-256 baselines and added/modified/missing file comparisons.
- Terminal tables, JSON reports, copy verification, and baseline inspection.
- Saved exclusions with root-anchored matching for in-tree baselines.
- Manifest validation, duplicate-key rejection, and atomic baseline writes.
- Explicit incomplete-scan results for read errors and changing files.
- Reproducible fictional-evidence demo and documented case study.
- Regression tests, lint/format checks, coverage enforcement, and package checks.
