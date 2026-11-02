"""Run from an installed checkout with its virtual environment's Python."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run(*args, expected=0, capture=False):
    print("\n$ iledger " + " ".join(str(arg) for arg in args), flush=True)
    result = subprocess.run(
        [sys.executable, "-m", "iledger", *(str(arg) for arg in args)],
        capture_output=capture,
        text=True,
    )
    if result.returncode != expected:
        raise RuntimeError(f"Expected exit {expected}, got {result.returncode}: {result.stderr}")
    return result.stdout


def main():
    # Unique folder on every run: never changes the user's own evidence.
    demo_root = Path(__file__).resolve().parents[1] / "demo-output"
    demo_root.mkdir(exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="case-", dir=demo_root))
    evidence = output / "evidence"
    evidence.mkdir()
    for name, content in {
        "notes.txt": "Interview at 09:00.\n",
        "access.log": "09:00 login success\n",
        "photo.txt": "Placeholder for a recovered image.\n",
    }.items():
        (evidence / name).write_text(content, encoding="utf-8")
    baseline = output / "baseline.json"
    run("baseline", evidence, "-o", baseline)
    run("check", baseline)
    (evidence / "notes.txt").write_text("Interview time changed to 11:00.\n", encoding="utf-8")
    (evidence / "photo.txt").unlink()
    (evidence / "new-file.txt").write_text("A file appeared after acquisition.\n", encoding="utf-8")
    run("check", baseline, expected=1)
    report = run("check", baseline, "--json", expected=1, capture=True)
    parsed = json.loads(report)
    assert parsed["added"] == ["new-file.txt"]
    assert parsed["modified"] == ["notes.txt"]
    assert parsed["missing"] == ["photo.txt"]
    (output / "report.json").write_text(report, encoding="utf-8")
    print(f"\nDemo passed. Files, baseline, and report are available at:\n{output}")


if __name__ == "__main__":
    main()
