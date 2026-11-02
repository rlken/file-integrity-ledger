# Case study: did the working evidence copy change?

## Scenario

A fictional case folder contains interview notes, an access log, and a text
placeholder representing a recovered image. Before working on the folder, capture
a baseline outside it. Later, compare the working copy against that baseline.

This exercise demonstrates integrity verification. It does not simulate forensic
acquisition or claim that these sample files are authentic evidence.

## Reproduce the exercise

From an installed checkout, run:

```sh
python scripts/demo.py
```

Every run creates a separate folder in `demo-output/` and prints its path. Inside
are `evidence/`, `baseline.json`, and `report.json`. The directory is ignored by Git
because reports can contain machine paths and file metadata.

The script first verifies that all three original files match the baseline. It
then changes the sample files and checks that the result contains exactly the
expected added, modified, and missing paths.

## Findings

| File | Deliberate action | Observed result | Supported conclusion |
| --- | --- | --- | --- |
| `access.log` | Left unchanged | Unchanged | Content matches its recorded fingerprint. |
| `notes.txt` | Change interview time from 09:00 to 11:00 | Modified | Current content differs from the baseline. |
| `photo.txt` | Remove the placeholder | Missing | The recorded path is absent from this scan. |
| `new-file.txt` | Create a file after the baseline | Added | The path was not present in the baseline. |

The final check returns exit code `1` because changes were found. The demo treats
this as the expected outcome, then parses the JSON report and verifies the paths.

Open `report.json` and look at `changes["notes.txt"]`: `before.sha256` is the
baseline fingerprint and `after.sha256` is the new fingerprint. The record also
contains sizes and modification times. For missing files, `after` is `null`; for
added files, `before` is `null`.

## Interpretation limits

A changed hash does not identify an actor, prove malicious intent, or explain the
change. A missing path is not proof of deletion: the file may have been renamed
or moved. A file's modification timestamp is mutable filesystem metadata, not a
trusted event timestamp. The report's `checked_at` records when the tool generated
the result, not when a change occurred.

Errors are kept separate from missing files. An unreadable directory yields an
incomplete scan, rather than presenting its unseen children as deleted evidence.
The baseline itself must be trusted; this project does not authenticate it.

## Further exercises

1. Rename `access.log`, check again, and explain the added/missing pair.
2. Change only a file's modification time; confirm that its content is unchanged.
3. Create a symbolic link; observe exit code `2` and inspect the error message.
4. Copy the evidence folder and use `--root` to verify the copy.
5. Change a byte in a large binary file; inspect the before/after SHA-256 values.

For a portfolio demonstration, walk through the scenario, explain the baseline
trust assumption, and show one failure case alongside the successful check.
