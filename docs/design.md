# Design notes

## Modules

| Module | Responsibility |
| --- | --- |
| `hashing.py` | Traverse folders, apply exclusions, fingerprint regular files. |
| `storage.py` | Validate and atomically save manifests; compare file records. |
| `cli.py` | Parse commands, format results, and choose process exit codes. |
| `scripts/demo.py` | Exercise the installed command with fictional evidence. |

## Why these choices?

**Streaming SHA-256.** The hash is computed in 1 MiB chunks, so a large individual
file does not need to fit into memory. The complete file-record dictionary does
remain in memory: metadata memory grows with the number and length of paths.
Total scan time is dominated by reading the included file bytes. Every check
rehashes contents; matching timestamps are never used as a shortcut.

**Relative paths.** A manifest stores the original absolute root and relative file
paths. `--root` selects another copy without rewriting the baseline. Reports
include absolute locations, which is useful locally but may reveal identifying
paths if a user publishes them.

**Versioned JSON.** Plain JSON is inspectable without the tool. A schema version
allows future incompatible formats to be rejected clearly. Validation checks
timestamps, paths, hash syntax, numeric fields, duplicate keys, conflicting file/
directory records, and records inconsistent with the declared exclusion scope.
Validation establishes format consistency, not authenticity.

**Exclusions are part of the baseline.** Checks reuse the same patterns, making
scope visible and repeatable. An in-tree baseline gets an exact root-anchored
exclusion, so another evidence file with the same basename is still included.

**Errors are not evidence of absence.** An unreadable file or subtree appears in
`errors` and makes the result `incomplete`. Its unobserved records are not labeled
missing. Successful reads from the same scan are still reported, but the result
does not claim the entire folder has been verified.

**Atomic manifest writes.** The tool writes JSON to a temporary file in the same
directory, flushes and syncs the file, then publishes it. A hard link provides
create-if-absent behavior; explicit `--force` uses atomic replacement. Failures
remove the temporary file. This requires a filesystem that supports those
operations and is not a guarantee of directory-entry durability after sudden
power loss.

**Live-file checks.** File identity, size, mtime, and ctime are checked around a
read to catch common races. Links and special files are rejected. This is not a
complete defense against a hostile filesystem or a substitute for a snapshot;
ancestor directories and later files can change during traversal.

## Manifest version 1

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer `1`. |
| `tool_version` | Version that wrote the baseline. |
| `algorithm` | `sha256`. |
| `created_at` | Timezone-aware ISO 8601 creation time (writer uses UTC). |
| `root` | Absolute path to the original scanned folder. |
| `excludes` | Ordered list of exclusion patterns. |
| `files` | Relative POSIX path → `{sha256, size, mtime_ns}`. |

File size is in bytes; `mtime_ns` is the filesystem modification time in
nanoseconds since the Unix epoch. Hashes are lowercase hexadecimal strings.
`tool_version` is informational; format compatibility is determined by
`schema_version` and `algorithm`.

## Check report version 1

A completed or incomplete scan returns `schema_version`, `status`, `checked_at`,
baseline path and creation time, selected root, algorithm, exclusions, three
sorted path lists (`added`, `modified`, `missing`), an `unchanged` count, `errors`,
and a `changes` mapping with before/after file records. Status is `unchanged`,
`changed`, or `incomplete`; any scan error takes precedence over content changes.

If loading the baseline or opening the root fails before scanning, `--json`
returns a smaller `{status: "error", error: "…"}` object with exit code `2`.
Command syntax errors are emitted by the CLI framework as terminal help/errors,
even when `--json` is present. Checks never update the baseline.

## Validation strategy

- Known SHA-256 vectors and multi-chunk binary reads check hashing correctness.
- CLI scenarios verify all three change types, copy verification, and exit codes.
- Failure injection checks unreadable files, failed writes, failed replacement,
  and files changing during reads without relying on unreliable permission tests.
- Invalid JSON and malformed records verify clean failures rather than tracebacks.
- Regression tests cover the in-tree baseline basename exclusion bug.
- CI runs formatting/lint checks, a 90% coverage floor, the executable demo, and
  an isolated wheel-install smoke test.

The CI matrix targets Python 3.9 and 3.14 on Linux and Python 3.14 on macOS.
