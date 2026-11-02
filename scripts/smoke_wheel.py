"""Install the built wheel in isolation and verify it on any supported OS."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    wheels = list((Path(__file__).resolve().parents[1] / "dist").glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit("Expected exactly one wheel in dist/. Remove old builds and rebuild.")
    with tempfile.TemporaryDirectory(prefix="iledger-wheel-") as directory:
        root = Path(directory)
        environment = root / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        cli = environment / ("Scripts/iledger.exe" if os.name == "nt" else "bin/iledger")
        subprocess.run([str(python), "-m", "pip", "install", str(wheels[0])], cwd=root, check=True)
        subprocess.run([str(cli), "--version"], cwd=root, check=True)
        evidence = root / "evidence with spaces"
        evidence.mkdir()
        sample = evidence / "sample.txt"
        sample.write_bytes(b"CRLF\r\ncontrol-z\x1aend\x00")
        subprocess.run(
            [str(cli), "baseline", str(evidence), "-o", "baseline.json"], cwd=root, check=True
        )
        subprocess.run([str(cli), "check", "baseline.json"], cwd=root, check=True)
        sample.write_bytes(b"changed")
        result = subprocess.run(
            [str(cli), "check", "baseline.json", "--json"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 1 or json.loads(result.stdout)["modified"] != ["sample.txt"]:
            raise RuntimeError(
                f"Installed wheel failed changed-file check: {result.stdout} {result.stderr}"
            )
        print("Isolated wheel installation and clean/changed checks passed.")


if __name__ == "__main__":
    main()
