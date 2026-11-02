"""Human-readable CLI with machine-readable check results."""

import json
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from . import __version__
from .hashing import DEFAULT_EXCLUDES, scan_directory
from .storage import compare_files, load_manifest, make_manifest, save_manifest, utc_now

app = typer.Typer(no_args_is_help=True, help="Fingerprint a folder, then see which files changed.")
console = Console()
err_console = Console(stderr=True)


@app.callback(invoke_without_command=True)
def main(
    version: bool = typer.Option(
        False, "--version", is_eager=True, help="Show the version and exit."
    ),
):
    if version:
        typer.echo(f"iledger {__version__}")
        raise typer.Exit()


def fail(error, as_json=False):
    if as_json:
        typer.echo(json.dumps({"status": "error", "error": str(error)}))
    else:
        err_console.print(Text("Error: " + str(error), style="red"))
    raise typer.Exit(2)


@app.command()
def baseline(
    folder: Path = typer.Argument(..., help="Folder to fingerprint recursively."),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Default: FOLDER/.iledger/baseline.json."
    ),
    exclude: Optional[List[str]] = typer.Option(
        None, "--exclude", "-x", help="Repeatable glob, saved with the baseline."
    ),
    force: bool = typer.Option(
        False, "--force", help="Replace an existing baseline intentionally."
    ),
):
    """Save a baseline of file contents. Incomplete scans are never saved."""
    try:
        root = folder.expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("scan target must be a directory")
        destination = (
            output.expanduser() if output else root / ".iledger/baseline.json"
        ).absolute()
        if destination.is_symlink():
            raise ValueError("baseline output cannot be a symbolic link")
        destination = destination.resolve()
        if destination.exists() and not force:
            raise ValueError("baseline already exists; use a new output path or --force")
        exclusions = list(DEFAULT_EXCLUDES) + (exclude or [])
        if any(not pattern for pattern in exclusions):
            raise ValueError("exclude patterns cannot be empty")
        try:
            relative = destination.relative_to(root).as_posix()
            # Escape glob metacharacters for the automatically excluded filename.
            exclusions.append(
                "/" + "".join({"[": "[[]", "*": "[*]", "?": "[?]"}.get(c, c) for c in relative)
            )
        except ValueError:
            pass
        files, errors = scan_directory(root, exclusions)
        if errors:
            for name, error in errors.items():
                err_console.print(Text(f"{name}: {error}"))
            raise ValueError(f"{len(errors)} scan error(s); no baseline was written")
        save_manifest(destination, make_manifest(root, files, exclusions), force)
    except (OSError, ValueError) as error:
        fail(error)
    console.print(Text(f"Saved baseline: {destination}", style="green"))
    console.print(f"{len(files)} file(s) · SHA-256")
    if not files:
        console.print("This baseline contains no files. Check your folder and exclusions.")


@app.command()
def check(
    baseline_path: Path = typer.Argument(..., help="Saved baseline JSON."),
    root: Optional[Path] = typer.Option(
        None, "--root", help="Check a copied folder instead of the original location."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print a JSON report to stdout."),
):
    """Compare contents. Exit codes: 0 unchanged, 1 changed, 2 incomplete/error."""
    try:
        manifest = load_manifest(baseline_path.expanduser())
        if root is None and not Path(manifest["root"]).is_absolute():
            raise ValueError("baseline root is from another platform; use --root to select a copy")
        target = (root.expanduser() if root else Path(manifest["root"])).resolve(strict=True)
        current, errors = scan_directory(target, manifest["excludes"])
        differences = compare_files(manifest["files"], current, errors)
        changed = any(differences[key] for key in ("added", "modified", "missing"))
        status = "incomplete" if errors else "changed" if changed else "unchanged"
        report = {
            "schema_version": 1,
            "status": status,
            "checked_at": utc_now(),
            "baseline": str(baseline_path.expanduser().resolve()),
            "baseline_created_at": manifest["created_at"],
            "root": str(target),
            "algorithm": "sha256",
            "excludes": manifest["excludes"],
            **differences,
            "errors": errors,
            "changes": {
                name: {"before": manifest["files"].get(name), "after": current.get(name)}
                for kind in ("added", "modified", "missing")
                for name in differences[kind]
            },
        }
    except (OSError, ValueError) as error:
        fail(error, as_json)
    if as_json:
        typer.echo(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        console.print(Text(f"Check: {status.upper()} — {target}"))
        console.print(
            f"{differences['unchanged']} unchanged · {len(differences['added'])} added · "
            f"{len(differences['modified'])} modified · {len(differences['missing'])} missing"
        )
        table = Table("Status", "Relative path", show_lines=False)
        for kind, color in (("added", "green"), ("modified", "yellow"), ("missing", "red")):
            for name in differences[kind]:
                table.add_row(Text(kind.upper(), style=color), Text(name))
        for name, error in errors.items():
            table.add_row(Text("ERROR", style="red"), Text(f"{name}: {error}"))
        if table.row_count:
            console.print(table)
        if errors:
            console.print("Scan incomplete: resolve the errors before relying on these results.")
    raise typer.Exit(2 if errors else 1 if changed else 0)


@app.command()
def inspect(baseline_path: Path = typer.Argument(..., help="Saved baseline JSON.")):
    """Show the baseline's scope and creation time without rescanning files."""
    try:
        manifest = load_manifest(baseline_path.expanduser())
    except (OSError, ValueError) as error:
        fail(error)
    for label, value in (
        ("Root", manifest["root"]),
        ("Created (UTC)", manifest["created_at"]),
        ("Algorithm", manifest["algorithm"]),
        ("Files", len(manifest["files"])),
        ("Excluded patterns", ", ".join(manifest["excludes"])),
    ):
        console.print(Text(f"{label}: {value}"))
